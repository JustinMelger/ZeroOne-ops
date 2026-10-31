"""Narrow normalized storage boundary for finding-sync orchestration."""

from typing import Protocol

from zeroone_ops.models.finding_sync import (
    FindingSyncInventory,
    FindingSyncRecord,
    FindingSyncWriteResult,
)
from zeroone_ops.models.work_item import WorkItemState


class FindingSyncStorage(Protocol):
    """Expose only the issue operations required by finding sync."""

    def load_inventory(self, *, repository_scope: str) -> FindingSyncInventory:
        """Load strict ownership inventory, including closed nonterminal batches."""
        ...

    def read_work_item(self, *, repository_scope: str, issue_number: int) -> FindingSyncRecord:
        """Re-read exact authority and native closure, rejecting malformed state."""
        ...

    def rediscover_batch(
        self, *, repository_scope: str, work_item_id: str
    ) -> tuple[FindingSyncRecord, ...]:
        """Find exact assigned identity in both issue states without creating work."""
        ...

    def validate_work_item_projection(self, work_item: WorkItemState) -> None:
        """Check the full serialized issue projection before transport."""
        ...

    def create_work_item(
        self, *, repository_scope: str, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Perform one create after shared ownership authorization, without retries."""
        ...

    def update_existing_work_item(
        self, *, repository_scope: str, existing: FindingSyncRecord, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Update the exact native snapshot represented by the record."""
        ...

    def close_work_item_issue(self, *, repository_scope: str, issue_number: int) -> None:
        """Close one provider issue after its authoritative state update."""
        ...

    def reopen_work_item_issue(self, *, repository_scope: str, issue_number: int) -> None:
        """Reopen one provider issue before rendering active state."""
        ...
