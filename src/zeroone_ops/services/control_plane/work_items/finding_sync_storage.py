"""Narrow normalized storage boundary for finding-sync orchestration."""

from collections.abc import Sequence
from typing import Protocol

from zeroone_ops.models.finding_sync import (
    FindingSyncInventory,
    FindingSyncRecord,
    FindingSyncWriteResult,
)
from zeroone_ops.models.work_item import WorkItemKind, WorkItemSourceRef, WorkItemState


class FindingSyncStorage(Protocol):
    """Expose only the issue operations required by finding sync."""

    def load_inventory(self, *, repository_scope: str) -> FindingSyncInventory:
        """Load open work and the three narrow closed indexes once."""
        ...

    def find_open_work_item_by_source(
        self, *, repository_scope: str, kind: WorkItemKind, source: WorkItemSourceRef
    ) -> FindingSyncRecord | None:
        """Re-read the uniquely matching open authoritative record."""
        ...

    def upsert_work_item(
        self,
        *,
        repository_scope: str,
        work_item: WorkItemState,
        dismissed_inventory: Sequence[FindingSyncRecord],
    ) -> FindingSyncWriteResult:
        """Create or reuse work, retaining the final dismissal guard."""
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
