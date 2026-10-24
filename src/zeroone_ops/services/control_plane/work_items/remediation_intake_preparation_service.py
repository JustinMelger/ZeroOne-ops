"""Prepare batch execution scope without claims or provider writes."""

from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.remediation_intake import RemediationIntakePreparation
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.remediation.batch_execution_scope_service import (
    BatchExecutionScopeService,
)


class RemediationIntakePreparationService:
    """Resolve batch scope while preserving revision failure routing."""

    def prepare(
        self, work_item: WorkItemState, *, policy: PolicyState | None, run_id: str | None
    ) -> RemediationIntakePreparation:
        """Return prepared state or a reason to block ordinary batch intake.

        Invalid queued revisions stay queued so execution can restore their
        authoritative review-feedback state instead of ordinary blocked state.
        """
        batch = work_item.batch
        if batch is None:
            return RemediationIntakePreparation(work_item)

        decision = BatchExecutionScopeService().resolve(work_item, policy, run_id=run_id)
        if decision.disposition == "blocked":
            if work_item.status == "review_revision_queued":
                return RemediationIntakePreparation(work_item)

            return RemediationIntakePreparation(
                work_item.model_copy(update={"status": "blocked", "claim": None}),
                blocking_reason=decision.reason or "Batch scope is unavailable.",
            )

        return RemediationIntakePreparation(
            work_item.model_copy(
                update={
                    "batch_attempt": work_item.batch_attempt
                    if work_item.status == "review_revision_queued"
                    else decision.attempt,
                    "batch": batch.model_copy(update={"selection_failure": None}),
                }
            )
        )
