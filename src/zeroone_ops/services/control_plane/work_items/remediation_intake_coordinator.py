"""Coordinate remediation selection and claims over normalized records."""

import logging
from collections.abc import Callable, Sequence
from datetime import datetime

from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.remediation_intake import RemediationIntakeOutcome, RemediationIntakeRecord
from zeroone_ops.models.work_item import WorkItemClaim, WorkItemExecutionFailure, WorkItemState
from zeroone_ops.services.control_plane.work_items.remediation_intake_ownership import (
    conflicting_intake_batches,
)
from zeroone_ops.services.control_plane.work_items.remediation_intake_preparation_service import (
    RemediationIntakePreparationService,
)
from zeroone_ops.services.control_plane.work_items.remediation_work_item_selection_service import (
    is_remediation_execution_eligible,
    remediation_execution_selection_key,
)
from zeroone_ops.services.remediation.remediation_execution_adapter import (
    control_plane_work_item_to_execution_target,
)

LOGGER = logging.getLogger(__name__)


class RemediationIntakeCoordinator:
    """Select and optionally claim one item using provider-local persistence."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        eligibility: Callable[[WorkItemState], bool] = is_remediation_execution_eligible,
        batch_policy: PolicyState | None = None,
        load_batch_policy: Callable[[], PolicyState] | None = None,
    ) -> None:
        """Retain the clock without reading time or accessing providers."""
        self.clock = clock
        self.eligibility = eligibility
        self.batch_policy = batch_policy
        self.load_batch_policy = load_batch_policy

    def select_and_claim(
        self,
        *,
        records: Sequence[RemediationIntakeRecord],
        persist_work_item: Callable[[WorkItemState], RemediationIntakeRecord],
        persist: bool = True,
        run_id: str | None = None,
    ) -> RemediationIntakeOutcome:
        """Select eligible work, optionally persist one claim, and build a target.

        Args:
            records: Complete parsed open inventory for this intake pass.
            persist_work_item: Provider-local write returning authoritative state.
            persist: Whether to persist a claim or preview the original selection.
            run_id: Optional correlation identifier for a persistent claim.

        Returns:
            The selected record and execution target, or an empty selection.
        """
        conflicts = conflicting_intake_batches(records)
        candidates = [
            record
            for record in records
            if self.eligibility(record.work_item)
            and (record.work_item.source.repository_scope, record.issue_number) not in conflicts
        ]
        candidates.sort(
            key=lambda record: remediation_execution_selection_key(
                record.work_item,
                created_at=record.created_at,
                provider_issue_number=record.issue_number,
            )
        )
        if (
            candidates
            and _needs_fresh_policy(candidates[0].work_item)
            and self.batch_policy is None
        ):
            try:
                if self.load_batch_policy is None:
                    raise RuntimeError("No authoritative policy loader configured.")
                self.batch_policy = self.load_batch_policy().model_copy(deep=True)
            except Exception:
                LOGGER.warning("Fresh batch intake withheld: authoritative policy unavailable.")
                candidates = [r for r in candidates if not _needs_fresh_policy(r.work_item)]
        if not candidates:
            return RemediationIntakeOutcome(
                selected_record=None, selected_target=None, item_count=len(records)
            )

        selected = candidates[0]
        preparation = RemediationIntakePreparationService().prepare(
            selected.work_item, policy=self.batch_policy, run_id=run_id
        )
        work_item = preparation.work_item
        if persist:
            timestamp = self.clock()
            if preparation.blocking_reason is not None:
                work_item = work_item.model_copy(
                    update={
                        "execution_failure": WorkItemExecutionFailure(
                            stage="issue_intake",
                            summary=preparation.blocking_reason,
                            retry_count=0,
                            run_id=run_id or "remediation",
                            occurred_at=timestamp,
                        )
                    }
                )
            else:
                work_item = work_item.model_copy(
                    update={
                        "status": "review_revision_queued"
                        if work_item.status == "review_revision_queued"
                        else "in_progress",
                        "claim": WorkItemClaim(claimed_at=timestamp, run_id=run_id),
                    }
                )
            selected = persist_work_item(work_item)
        elif work_item is not selected.work_item:
            selected = RemediationIntakeRecord(
                work_item, selected.issue_number, selected.issue_url, selected.created_at
            )

        return RemediationIntakeOutcome(
            selected_record=selected,
            selected_target=control_plane_work_item_to_execution_target(
                selected.work_item, work_item_url=selected.issue_url
            ),
            item_count=len(records),
            batch_policy=self.batch_policy,
        )


def _needs_fresh_policy(work_item: WorkItemState) -> bool:
    """Recorded publication and revision scope must not depend on fresh policy access."""
    return (
        work_item.batch is not None
        and work_item.publication_retry is None
        and work_item.status != "review_revision_queued"
    )
