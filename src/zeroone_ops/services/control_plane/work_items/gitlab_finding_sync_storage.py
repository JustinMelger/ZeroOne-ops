"""GitLab transport adapter for normalized finding-sync operations."""

from collections.abc import Sequence

from zeroone_ops.models.finding_sync import (
    FindingSyncInventory,
    FindingSyncRecord,
    FindingSyncWriteResult,
)
from zeroone_ops.models.work_item import WorkItemKind, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_upsert_service import (
    GitLabWorkItemUpsertResult,
)


class GitLabFindingSyncStorage:
    """Translate normalized sync operations without deciding workflow policy."""

    def __init__(self, work_item_service: GitLabWorkItemService) -> None:
        """Retain transport and native snapshots without performing I/O."""
        self.work_item_service = work_item_service
        # Keep each normalized record alive and preserve its exact native snapshot.
        self._snapshots: dict[int, tuple[FindingSyncRecord, GitLabWorkItemLookupResult]] = {}
        self._projection_state: dict[int, bool] = {}

    def load_inventory(self, *, repository_scope: str) -> FindingSyncInventory:
        """Load the same four indexed inventories in their original order."""
        return FindingSyncInventory(
            open_work_items=tuple(
                self._record_from(result)
                for result in self.work_item_service.list_open_work_items(
                    project_id=repository_scope
                )
            ),
            policy_deferred_work_items=tuple(
                self._record_from(result)
                for result in self.work_item_service.list_closed_policy_deferred_work_items(
                    project_id=repository_scope
                )
            ),
            capacity_deferred_work_items=tuple(
                self._record_from(result)
                for result in self.work_item_service.list_closed_capacity_deferred_work_items(
                    project_id=repository_scope
                )
            ),
            dismissed_work_items=tuple(
                self._record_from(result)
                for result in self.work_item_service.list_closed_dismissed_work_items(
                    project_id=repository_scope
                )
            ),
        )

    def find_open_work_item_by_source(
        self, *, repository_scope: str, kind: WorkItemKind, source: WorkItemSourceRef
    ) -> FindingSyncRecord | None:
        """Normalize an authoritative re-read without replacing earlier snapshots."""
        result = self.work_item_service.find_open_work_item_by_source(
            project_id=repository_scope, kind=kind, source=source
        )
        return self._record_from(result) if result is not None else None

    def upsert_work_item(
        self,
        *,
        repository_scope: str,
        work_item: WorkItemState,
        dismissed_inventory: Sequence[FindingSyncRecord],
    ) -> FindingSyncWriteResult:
        """Preserve native upsert and its defensive dismissal recheck."""
        result = self.work_item_service.upsert_work_item(
            project_id=repository_scope,
            work_item=work_item,
            dismissed_inventory=[self._native_record(record) for record in dismissed_inventory],
        )
        return self._write_result(result, is_open=result.action != "suppressed")

    def update_existing_work_item(
        self, *, repository_scope: str, existing: FindingSyncRecord, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Update using the native lookup corresponding to the supplied snapshot."""
        result = self.work_item_service.update_existing_work_item(
            project_id=repository_scope, existing=self._native_record(existing), work_item=work_item
        )
        return self._write_result(
            result, is_open=self._projection_state.get(existing.issue_number, existing.is_open)
        )

    def close_work_item_issue(self, *, repository_scope: str, issue_number: int) -> None:
        """Close one native issue without changing persisted workflow state."""
        self.work_item_service.close_work_item_issue(
            project_id=repository_scope, issue_iid=issue_number
        )
        self._projection_state[issue_number] = False

    def reopen_work_item_issue(self, *, repository_scope: str, issue_number: int) -> None:
        """Reopen one native issue without changing persisted workflow state."""
        self.work_item_service.reopen_work_item_issue(
            project_id=repository_scope, issue_iid=issue_number
        )
        self._projection_state[issue_number] = True

    def _record_from(self, result: GitLabWorkItemLookupResult) -> FindingSyncRecord:
        """Retain the native snapshot behind its normalized record."""
        record = FindingSyncRecord(
            work_item=result.work_item,
            issue_number=result.issue.iid,
            issue_url=result.issue.web_url,
            is_open=result.is_open,
        )
        self._snapshots[id(record)] = (record, result)
        return record

    def _native_record(self, record: FindingSyncRecord) -> GitLabWorkItemLookupResult:
        """Recover the exact snapshot rather than the latest issue with that number."""
        return self._snapshots[id(record)][1]

    def _write_result(
        self, result: GitLabWorkItemUpsertResult, *, is_open: bool
    ) -> FindingSyncWriteResult:
        """Normalize the actual state and issue returned by persistence."""
        record = self._record_from(
            GitLabWorkItemLookupResult(
                issue=result.issue,
                work_item=result.work_item,
                is_open=is_open,
            )
        )
        return FindingSyncWriteResult(record=record, action=result.action)
