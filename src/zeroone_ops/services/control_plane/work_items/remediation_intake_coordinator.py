"""Coordinate remediation selection and claims over normalized records."""

from collections.abc import Callable, Sequence
from datetime import datetime

from zeroone_ops.models.remediation_intake import RemediationIntakeOutcome, RemediationIntakeRecord
from zeroone_ops.models.work_item import WorkItemClaim, WorkItemState
from zeroone_ops.services.control_plane.work_items.remediation_work_item_selection_service import (
    is_remediation_execution_eligible,
    remediation_execution_selection_key,
)
from zeroone_ops.services.remediation.remediation_execution_adapter import (
    control_plane_work_item_to_execution_target,
)


class RemediationIntakeCoordinator:
    """Select and optionally claim one item using provider-local persistence."""

    def __init__(self, *, clock: Callable[[], datetime]) -> None:
        """Retain the clock without reading time or accessing providers."""
        self.clock = clock

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
        candidates = [
            record for record in records if is_remediation_execution_eligible(record.work_item)
        ]
        if not candidates:
            return RemediationIntakeOutcome(
                selected_record=None, selected_target=None, item_count=len(records)
            )
        selected = min(
            candidates,
            key=lambda record: remediation_execution_selection_key(
                record.work_item,
                created_at=record.created_at,
                provider_issue_number=record.issue_number,
            ),
        )
        if persist:
            claimed = selected.work_item.model_copy(
                update={
                    "status": (
                        "review_revision_queued"
                        if selected.work_item.status == "review_revision_queued"
                        else "in_progress"
                    ),
                    "claim": WorkItemClaim(claimed_at=self.clock(), run_id=run_id),
                }
            )
            selected = persist_work_item(claimed)
        return RemediationIntakeOutcome(
            selected_record=selected,
            selected_target=control_plane_work_item_to_execution_target(
                selected.work_item, work_item_url=selected.issue_url
            ),
            item_count=len(records),
        )
