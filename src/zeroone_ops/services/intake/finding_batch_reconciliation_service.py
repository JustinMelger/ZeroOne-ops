"""Pure observation and reconciliation decisions for internal batch finding sync."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.finding_batch import BatchSelectionFailure, WorkItemBatch
from zeroone_ops.models.finding_batch_promotion import (
    FindingBatchMemberIdentity,
)
from zeroone_ops.models.finding_batch_sync import BatchSyncContext, PreparedBatchWorkItem
from zeroone_ops.models.finding_sync import FindingSyncRecord
from zeroone_ops.models.work_item import (
    WorkItemCapacityDeferral,
    WorkItemPolicyDeferral,
    WorkItemState,
)
from zeroone_ops.services.intake.finding_batch_observation_service import refresh_batch_observations
from zeroone_ops.services.intake.finding_batch_ownership import (
    is_safe_unstarted_batch,
    retains_finding_batch_ownership,
)
from zeroone_ops.services.intake.finding_batch_promotion_service import (
    batch_requirements_compatible,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import FindingWorkflowPolicyService

_SELECTABLE_STATUSES = {"candidate", "approved", "policy_deferred", "capacity_deferred"}


class FindingBatchReconciliationService:
    """Decide safe batch transitions without clocks, providers, logging, or counter mutation."""

    def __init__(self, policy: FindingWorkflowPolicyService | None = None) -> None:
        """Retain the shared per-finding policy evaluator without side effects."""
        self.policy = policy or FindingWorkflowPolicyService()

    def prepare(
        self,
        record: FindingSyncRecord,
        findings: Mapping[tuple[str, str], NormalizedFinding],
        managed: set[str],
        context: BatchSyncContext,
        suppressed: frozenset[FindingBatchMemberIdentity],
    ) -> PreparedBatchWorkItem:
        """Refresh observations first, then decide only safe unstarted inventory transitions."""
        run_id, now = context.run_id, context.now
        state = record.work_item.model_copy(deep=True)
        if not retains_finding_batch_ownership(record):
            return PreparedBatchWorkItem(record, state, False)
        safe = _is_reconcilable(record)
        mismatches: tuple[str, ...] = ()
        if state.batch is not None and state.status not in {"completed", "dismissed"}:
            refresh = refresh_batch_observations(
                batch=state.batch,
                findings=findings,
                managed_source_ids=managed,
                run_id=run_id,
                now=now,
            )
            state = state.model_copy(update={"batch": refresh.batch})
            mismatches = refresh.scope_mismatch_ids
        if not safe:
            return PreparedBatchWorkItem(
                record,
                state,
                False,
                selection_reason=(
                    state.batch.selection_failure.reason
                    if state.batch and state.batch.selection_failure
                    else None
                ),
            )

        return self._reconcile_detected(
            record, state, findings, managed, context, suppressed, mismatches
        )

    def _reconcile_detected(
        self,
        record: FindingSyncRecord,
        state: WorkItemState,
        findings: Mapping[tuple[str, str], NormalizedFinding],
        managed: set[str],
        context: BatchSyncContext,
        suppressed: frozenset[FindingBatchMemberIdentity],
        mismatches: tuple[str, ...],
    ) -> PreparedBatchWorkItem:
        """Evaluate scope, absence, and executable requirements in their existing precedence."""
        members = _detected_members(state, findings)
        if state.batch is None and members:
            current = members[0]
            state = state.model_copy(
                update={
                    "summary": current.title,
                    "detail": current.summary,
                    "severity": current.severity,
                    "file_path": current.repository_path,
                    "line": current.line_start,
                    "remediation_context": current.remediation_context.model_copy(deep=True),
                }
            )

        if mismatches:
            blocked = _block_selection(
                state, "batch_scope_mismatch", mismatches, context.run_id, context.now
            )
            return PreparedBatchWorkItem(
                record, blocked, True, selection_reason="batch_scope_mismatch"
            )
        if _all_absent(state, findings, managed):
            state = state.model_copy(
                update={
                    "status": "completed",
                    "resolution": "no_longer_detected",
                    "policy_deferral": None,
                    "capacity_deferral": None,
                }
            )
            return PreparedBatchWorkItem(record, state, True)
        if not members:
            return PreparedBatchWorkItem(record, state, True)

        return self._reconcile_present(record, state, members, context, suppressed)

    def _reconcile_present(
        self,
        record: FindingSyncRecord,
        state: WorkItemState,
        members: Sequence[NormalizedFinding],
        context: BatchSyncContext,
        suppressed: frozenset[FindingBatchMemberIdentity],
    ) -> PreparedBatchWorkItem:
        """Filter members before compatibility checks, without dropping frozen membership."""
        executable = [
            member
            for member in members
            if self.policy.decide_promotion(
                finding=member, policy_state=context.policy_state
            ).disposition
            == "promote"
            and (
                state.source.repository_scope or "",
                member.source_id,
                member.finding_id,
                "remediation",
            )
            not in suppressed
        ]
        if not executable:
            deferred = state.model_copy(
                update={
                    "status": "policy_deferred",
                    "capacity_deferral": None,
                    "policy_deferral": WorkItemPolicyDeferral(
                        reason="policy_ineligible", run_id=context.run_id, occurred_at=context.now
                    )
                    if context.now
                    else state.policy_deferral,
                }
            )
            return PreparedBatchWorkItem(record, deferred, True)

        if (
            state.batch is not None
            and len(executable) > 1
            and not batch_requirements_compatible(executable)
        ):
            blocked = _block_selection(
                state,
                "batch_requirements_mismatch",
                tuple(member.finding_id for member in executable),
                context.run_id,
                context.now,
            )
            return PreparedBatchWorkItem(record, blocked, True, True, "batch_requirements_mismatch")

        eligible = state.model_copy(
            update={
                "severity": _highest_severity_member(executable).severity,
                "remediation_context": executable[0].remediation_context.model_copy(deep=True),
            }
        )
        return PreparedBatchWorkItem(record, eligible, True, True)

    def capacity_state(
        self,
        entry: PreparedBatchWorkItem,
        selected: bool,
        context: BatchSyncContext,
    ) -> WorkItemState:
        """Allocate only eligible unstarted units; never demote an eligible approved owner."""
        run_id, now = context.run_id, context.now
        state = entry.work_item
        if not entry.reconcilable or state.status in {"blocked", "completed", "approved"}:
            return state
        if not entry.capacity_eligible:
            return state
        if selected:
            return state.model_copy(
                update={"status": "approved", "policy_deferral": None, "capacity_deferral": None}
            )
        return state.model_copy(
            update={
                "status": "capacity_deferred",
                "policy_deferral": None,
                "capacity_deferral": WorkItemCapacityDeferral(
                    reason="promotion_capacity_exhausted", run_id=run_id, occurred_at=now
                )
                if now
                else state.capacity_deferral,
            }
        )


def _is_reconcilable(record: FindingSyncRecord) -> bool:
    """Exclude history-bearing batches and protected work from policy/capacity transitions."""
    state = record.work_item
    if (
        state.status not in _SELECTABLE_STATUSES
        or state.claim is not None
        or state.linked_change_request is not None
        or not retains_finding_batch_ownership(record)
    ):
        return False
    return state.batch is None or is_safe_unstarted_batch(
        state.model_copy(update={"status": "candidate"})
    )


def _detected_members(
    state: WorkItemState, findings: Mapping[tuple[str, str], NormalizedFinding]
) -> list[NormalizedFinding]:
    """Use last confirmed batch evidence without reviving absent members on unavailable scans."""
    if state.batch is None:
        current = findings.get((state.source.source, state.source.source_item_key))
        return [current] if current else []
    originals = {member.finding_id: member for member in state.batch.members}
    return [
        (observation.last_confirmed_finding or originals[observation.finding_id]).to_finding()
        for observation in state.batch.observations
        if observation.last_confirmed_presence == "detected"
    ]


def _all_absent(
    state: WorkItemState, findings: Mapping[tuple[str, str], NormalizedFinding], managed: set[str]
) -> bool:
    """Require complete source ownership in this run, not just earlier absence observations."""
    if state.source.source not in managed:
        return False
    if state.batch is None:
        return (state.source.source, state.source.source_item_key) not in findings
    return all(
        observation.last_confirmed_presence == "absent" and observation.freshness == "current"
        for observation in state.batch.observations
    )


def _block_selection(
    state: WorkItemState,
    reason: str,
    member_ids: tuple[str, ...],
    run_id: str,
    now: datetime | None,
) -> WorkItemState:
    """Retain ownership and bound persistent evidence; dry runs create no persistence timestamp."""
    if state.batch is None:
        raise ValueError("Selection-failure evidence requires batch state.")
    batch = state.batch
    if now is not None:
        ordered = sorted(set(member_ids))
        failure = BatchSelectionFailure.model_validate(
            dict(
                reason=reason,
                run_id=run_id,
                occurred_at=now,
                member_ids=ordered[:10],
                omitted_member_count=max(len(ordered) - 10, 0),
            )
        )
        batch = WorkItemBatch.model_validate(batch.model_dump() | {"selection_failure": failure})
    return state.model_copy(
        update={
            "status": "blocked",
            "batch": batch,
            "policy_deferral": None,
            "capacity_deferral": None,
        }
    )


def _highest_severity_member(members: Sequence[NormalizedFinding]) -> NormalizedFinding:
    return min(members, key=lambda member: {"high": 0, "medium": 1, "low": 2}[member.severity])
