"""Resolve immutable batch attempt scopes without providers or scanner inference."""

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.batch_execution import BatchAttemptEvidence
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.intake.finding_batch_promotion_service import (
    batch_requirements_compatible,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import FindingWorkflowPolicyService


@dataclass(frozen=True)
class BatchExecutionScopeDecision:
    """Separate executable scope from absence and bounded selection failures."""

    disposition: Literal["execute", "all_absent", "blocked"]
    attempt: BatchAttemptEvidence | None = None
    reason: str | None = None


class BatchExecutionScopeService:
    """Select original members only; retries and revisions never acquire new scope."""

    def resolve(
        self, work_item: WorkItemState, policy: PolicyState, *, run_id: str | None = None
    ) -> BatchExecutionScopeDecision:
        """Choose recorded publication/revision scope before fresh observation assessment."""
        batch = work_item.batch
        if batch is None:
            return BatchExecutionScopeDecision("blocked", reason="Batch state is missing.")
        if work_item.publication_retry is not None or work_item.status == "review_revision_queued":
            attempt = (
                work_item.publication_retry.batch_attempt
                if work_item.publication_retry is not None
                else work_item.batch_attempt
            )
            if attempt is None or attempt.batch_id != work_item.work_item_id:
                return BatchExecutionScopeDecision(
                    "blocked", reason="Recorded batch attempt is missing."
                )
            if attempt.coverage is None or attempt.coverage.unaddressable:
                return BatchExecutionScopeDecision(
                    "blocked", reason="Recorded batch coverage is incomplete."
                )
            return BatchExecutionScopeDecision("execute", attempt)

        observations = batch.observations
        if all(o.last_confirmed_presence == "absent" for o in observations):
            if all(o.freshness == "current" for o in observations):
                return BatchExecutionScopeDecision("all_absent")
            return BatchExecutionScopeDecision("blocked", reason="Absence evidence is not current.")
        if batch.selection_failure and batch.selection_failure.reason == "batch_scope_mismatch":
            affected = set(batch.selection_failure.member_ids)
            if any(
                (o.finding_id in affected or batch.selection_failure.omitted_member_count > 0)
                and o.freshness != "current"
                for o in observations
            ):
                return BatchExecutionScopeDecision(
                    "blocked", reason="Member scope mismatch remains unresolved."
                )

        members = FindingWorkflowPolicyService().eligible_batch_members(work_item, policy)
        if not members:
            return BatchExecutionScopeDecision(
                "blocked", reason="No remaining members are policy eligible."
            )
        if not batch_requirements_compatible([member.to_finding() for member in members]):
            return BatchExecutionScopeDecision(
                "blocked", reason="Executable member requirements are incompatible."
            )
        return BatchExecutionScopeDecision(
            "execute",
            BatchAttemptEvidence(
                batch_id=work_item.work_item_id,
                attempt_number=work_item.attempt_number,
                run_id=run_id,
                members=members,
                observation_run_ids=tuple(
                    sorted({o.last_confirmed_sync_run_id or o.sync_run_id for o in observations})
                ),
            ),
        )
