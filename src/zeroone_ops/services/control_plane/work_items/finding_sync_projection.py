"""Share provider-neutral issue projection ordering without owning state decisions."""

from zeroone_ops.models.finding_sync import FindingSyncRecord, FindingSyncWriteResult
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.work_items.finding_sync_storage import FindingSyncStorage


class FindingSyncProjection:
    """Apply already-decided state transitions through normalized storage."""

    def __init__(self, storage: FindingSyncStorage) -> None:
        """Retain transport without performing reads or writes."""
        self.storage = storage

    def close(
        self, repository_scope: str, existing: FindingSyncRecord, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Persist terminal/deferred authority before closing its provider projection."""
        result = self.storage.update_existing_work_item(
            repository_scope=repository_scope, existing=existing, work_item=work_item
        )
        if existing.is_open:
            self.storage.close_work_item_issue(
                repository_scope=repository_scope, issue_number=existing.issue_number
            )
        return result

    def activate(
        self, repository_scope: str, existing: FindingSyncRecord, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Reopen before rendering an active state; never create another issue."""
        if not existing.is_open:
            self.storage.reopen_work_item_issue(
                repository_scope=repository_scope, issue_number=existing.issue_number
            )
        return self.storage.update_existing_work_item(
            repository_scope=repository_scope, existing=existing, work_item=work_item
        )

    def block(
        self, repository_scope: str, existing: FindingSyncRecord, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Persist the non-executable blocker before making a deferred issue visible."""
        result = self.storage.update_existing_work_item(
            repository_scope=repository_scope, existing=existing, work_item=work_item
        )
        if not existing.is_open:
            self.storage.reopen_work_item_issue(
                repository_scope=repository_scope, issue_number=existing.issue_number
            )
        return result
