"""Guard batch issue projections without deciding reconciliation or reporting."""

from dataclasses import replace

from zeroone_ops.models.finding_batch_sync import BatchProjectionOutcome
from zeroone_ops.models.finding_sync import FindingSyncRecord
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.work_items.batch_finding_sync_storage import (
    BatchFindingSyncStorage,
)
from zeroone_ops.services.control_plane.work_items.finding_sync_projection import (
    FindingSyncProjection,
)
from zeroone_ops.services.shared.projection_payload import ProjectionSizeExceeded

_CLOSED_STATUSES = {"completed", "dismissed", "policy_deferred", "capacity_deferred"}


class BatchFindingSyncProjection:
    """Apply read-before-write guards and return explicit transport outcomes."""

    def __init__(self, storage: BatchFindingSyncStorage) -> None:
        """Retain transport and shared ordering without performing I/O."""
        self.storage = storage
        self.projection = FindingSyncProjection(storage)

    def project(
        self,
        scope: str,
        existing: FindingSyncRecord,
        desired: WorkItemState,
        *,
        persist: bool,
    ) -> BatchProjectionOutcome:
        """Re-read exact authority before writing; dry runs return a simulated record."""
        previous_status = existing.work_item.status
        needs_repair = (existing.is_open and desired.status in _CLOSED_STATUSES) or (
            not existing.is_open
            and desired.status == "blocked"
            and desired.batch is not None
            and desired.batch.selection_failure is not None
        )
        if desired == existing.work_item and not needs_repair:
            return BatchProjectionOutcome(previous_status, record=existing)

        try:
            current = self.storage.read_work_item(
                repository_scope=scope, issue_number=existing.issue_number
            )
            if current.work_item != existing.work_item or current.is_open != existing.is_open:
                return BatchProjectionOutcome(
                    previous_status,
                    warnings=("Batch projection retained concurrently changed authority",),
                )
            self.storage.validate_work_item_projection(desired)
            if not persist:
                return BatchProjectionOutcome(
                    previous_status, record=replace(current, work_item=desired)
                )

            if desired.status in _CLOSED_STATUSES:
                result = self.projection.close(scope, current, desired)
            elif desired.status == "blocked" and desired.batch and desired.batch.selection_failure:
                result = self.projection.block(scope, current, desired)
            elif desired.status == "approved" and previous_status != "approved":
                result = self.projection.activate(scope, current, desired)
            else:
                result = self.storage.update_existing_work_item(
                    repository_scope=scope, existing=current, work_item=desired
                )
            return BatchProjectionOutcome(
                previous_status, record=result.record, write_action=result.action
            )
        except ProjectionSizeExceeded:
            return BatchProjectionOutcome(
                previous_status,
                warnings=(
                    "Batch projection withheld: projection_size_exceeded; authority retained.",
                ),
            )
        except Exception:
            return BatchProjectionOutcome(
                previous_status,
                warnings=("Batch work-item projection failed; later sync may repair it",),
            )
