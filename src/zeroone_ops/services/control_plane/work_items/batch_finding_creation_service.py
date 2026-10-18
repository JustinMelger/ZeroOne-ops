"""Authorize and publish one internal batch unit without owning run reporting."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import PurePosixPath
from uuid import uuid4

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.finding_batch import BatchMemberObservation, WorkItemBatch
from zeroone_ops.models.finding_batch_promotion import (
    FindingBatchPromotionPlan,
    FindingBatchPromotionUnit,
)
from zeroone_ops.models.finding_batch_snapshot import BatchFindingSnapshot
from zeroone_ops.models.finding_batch_sync import (
    BatchCreationOutcome,
    BatchSyncContext,
    PreparedBatchWorkItem,
)
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.work_items.batch_finding_sync_storage import (
    BatchFindingSyncStorage,
    inventory_records,
)
from zeroone_ops.services.intake.finding_batch_identity import create_finding_batch_identity
from zeroone_ops.services.intake.finding_batch_ownership import build_finding_batch_ownership
from zeroone_ops.services.intake.finding_batch_promotion_service import FindingBatchPromotionService

_UNCERTAIN_CREATE = "Batch create outcome is uncertain; no create retry will be attempted"
_OWNERSHIP_UNAVAILABLE = "Batch creation withheld because ownership could not be established"


class BatchFindingCreationService:
    """Own pre-create authorization and uncertain-write recovery, never aggregate counters."""

    def __init__(
        self, storage: BatchFindingSyncStorage, planner: FindingBatchPromotionService
    ) -> None:
        """Retain normalized transport and the shared planner without performing I/O."""
        self.storage = storage
        self.planner = planner

    def publish(
        self,
        unit: FindingBatchPromotionUnit,
        context: BatchSyncContext,
        simulated: Sequence[PreparedBatchWorkItem] = (),
    ) -> BatchCreationOutcome:
        """Recheck authority before allocating identity; dry runs perform only the same reads."""
        try:
            rechecked = self._recheck(unit, context, simulated)
            if not any(
                _unit_key(candidate) == _unit_key(unit) for candidate in rechecked.selected_new
            ):
                return BatchCreationOutcome(
                    backlog_reason_counts=Counter(
                        decision.reason if decision.reason != "selected" else "ownership_changed"
                        for decision in rechecked.decisions
                    ),
                    warnings=("Batch creation withheld after ownership recheck",),
                )
            if not context.persist:
                return BatchCreationOutcome(selected_member_count=len(unit.members))

            if context.now is None:
                raise ValueError("Live batch creation requires an observation timestamp.")
            work_item = _new_work_item(unit, context.repository_scope, context.run_id, context.now)
            return self._create_once(work_item, context, len(unit.members))
        except Exception:
            # Failed authority reads cannot authorize creation, even if earlier reads succeeded.
            return BatchCreationOutcome(
                backlog_reason_counts={"ownership_unavailable": len(unit.members)},
                warnings=(_OWNERSHIP_UNAVAILABLE,),
            )

    def _recheck(
        self,
        unit: FindingBatchPromotionUnit,
        context: BatchSyncContext,
        simulated: Sequence[PreparedBatchWorkItem],
    ) -> FindingBatchPromotionPlan:
        """Overlay dry-run decisions only when freshly read authority still matches its original."""
        fresh = inventory_records(
            self.storage.load_batch_inventory(repository_scope=context.repository_scope)
        )
        if not context.persist:
            by_number = {entry.original.issue_number: entry for entry in simulated}
            fresh = tuple(
                replace(record, work_item=by_number[record.issue_number].work_item)
                if record.issue_number in by_number
                and record == by_number[record.issue_number].original
                else record
                for record in fresh
            )
        return self.planner.plan(
            findings=unit.members,
            records=fresh,
            policy_state=context.policy_state,
            repository_scope=context.repository_scope,
            max_active_work_items=context.max_active_work_items,
            max_findings_per_work_item=context.max_findings_per_work_item,
            source_priorities=context.source_priorities,
        )

    def _create_once(
        self,
        work_item: WorkItemState,
        context: BatchSyncContext,
        proposed_member_count: int,
    ) -> BatchCreationOutcome:
        """Return actual persistence evidence; invalid or failed responses enter rediscovery."""
        try:
            result = self.storage.create_work_item(
                repository_scope=context.repository_scope, work_item=work_item
            )
            if (
                result.record.work_item.work_item_id != work_item.work_item_id
                or result.record.work_item.source.repository_scope != context.repository_scope
                or (
                    work_item.batch is not None
                    and (
                        result.record.work_item.batch is None
                        or result.record.work_item.batch.group != work_item.batch.group
                    )
                )
            ):
                raise ValueError("Create response changed assigned identity.")
        except Exception:
            return self._rediscover(work_item, context, proposed_member_count)

        return BatchCreationOutcome(
            record=result.record,
            write_action=result.action,
            selected_member_count=len(result.record.work_item.batch.members)
            if result.record.work_item.batch
            else 1,
        )

    def _rediscover(
        self,
        work_item: WorkItemState,
        context: BatchSyncContext,
        proposed_member_count: int,
    ) -> BatchCreationOutcome:
        """Never retry a create; ambiguity and failed discovery preserve both warning causes."""
        if work_item.batch is not None:
            try:
                matches = self.storage.rediscover_batch(
                    repository_scope=context.repository_scope, work_item_id=work_item.work_item_id
                )
                ownership = build_finding_batch_ownership(
                    records=inventory_records(
                        self.storage.load_batch_inventory(repository_scope=context.repository_scope)
                    ),
                    repository_scope=context.repository_scope,
                )
                if (
                    len(matches) == 1
                    and matches[0].is_open
                    and matches[0].work_item.status == "approved"
                    and matches[0].issue_number not in ownership.conflict_issues
                ):
                    persisted = matches[0]
                    return BatchCreationOutcome(
                        record=persisted,
                        write_action="unchanged",
                        selected_member_count=len(persisted.work_item.batch.members)
                        if persisted.work_item.batch
                        else 1,
                        warnings=(_UNCERTAIN_CREATE,),
                    )
            except Exception:
                return BatchCreationOutcome(
                    backlog_reason_counts={"ownership_unavailable": proposed_member_count},
                    warnings=(_UNCERTAIN_CREATE, _OWNERSHIP_UNAVAILABLE),
                )
        return BatchCreationOutcome(
            backlog_reason_counts={"creation_unconfirmed": proposed_member_count},
            warnings=(_UNCERTAIN_CREATE,),
        )


def _unit_key(unit: FindingBatchPromotionUnit) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((member.source_id, member.finding_id) for member in unit.members))


def _highest_severity_member(members: Sequence[NormalizedFinding]) -> NormalizedFinding:
    return min(members, key=lambda member: {"high": 0, "medium": 1, "low": 2}[member.severity])


def _new_work_item(
    unit: FindingBatchPromotionUnit, scope: str, run_id: str, now: datetime
) -> WorkItemState:
    """Freeze all selected evidence and allocate one durable identity only after authorization."""
    first = unit.members[0]
    batch = None
    source_key = first.finding_id
    if unit.group is not None:
        identity = create_finding_batch_identity()
        identifier, source_key = identity.work_item_id, identity.source_item_key
        batch = WorkItemBatch(
            group=unit.group,
            members=tuple(BatchFindingSnapshot.model_validate(member) for member in unit.members),
            observations=tuple(
                BatchMemberObservation(
                    finding_id=member.finding_id,
                    last_confirmed_presence="detected",
                    freshness="current",
                    sync_run_id=run_id,
                    observed_at=now,
                    last_confirmed_sync_run_id=run_id,
                    last_confirmed_finding=BatchFindingSnapshot.model_validate(member),
                )
                for member in unit.members
            ),
        )
    else:
        identifier = f"work-{uuid4().hex}"
    return WorkItemState(
        work_item_id=identifier,
        kind="remediation",
        status="approved",
        source=WorkItemSourceRef(
            source=first.source_id, source_item_key=source_key, repository_scope=scope
        ),
        summary=(
            f"Remediate {len(unit.members)} {unit.group.rule_id} findings in "
            f"{PurePosixPath(unit.group.file_path).name}"
            if unit.group
            else first.title
        ),
        detail=None if batch else first.summary,
        severity=_highest_severity_member(unit.members).severity,
        file_path=first.repository_path,
        line=first.line_start,
        remediation_context=first.remediation_context.model_copy(deep=True),
        batch=batch,
    )
