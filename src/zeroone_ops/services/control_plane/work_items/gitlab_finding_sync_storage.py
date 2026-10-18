"""GitLab transport adapter for normalized finding-sync operations."""

from collections.abc import Sequence

from zeroone_ops.models.finding_sync import (
    FindingSyncInventory,
    FindingSyncRecord,
    FindingSyncWriteResult,
)
from zeroone_ops.models.work_item import WorkItemKind, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.work_items.batch_finding_sync_storage import (
    load_batch_inventory,
    rediscover_batch,
)
from zeroone_ops.services.control_plane.work_items.finding_sync_record_store import (
    FindingSyncRecordStore,
)
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
        self._records = FindingSyncRecordStore[GitLabWorkItemLookupResult]()

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
            dismissed_inventory=[
                self._records.native_record(record) for record in dismissed_inventory
            ],
        )
        return self._write_result(result, is_open=result.action != "suppressed")

    def update_existing_work_item(
        self, *, repository_scope: str, existing: FindingSyncRecord, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Update using the native lookup corresponding to the supplied snapshot."""
        result = self.work_item_service.update_existing_work_item(
            project_id=repository_scope,
            existing=self._records.native_record(existing),
            work_item=work_item,
        )
        return self._write_result(result, is_open=self._records.projected_is_open(existing))

    def close_work_item_issue(self, *, repository_scope: str, issue_number: int) -> None:
        """Close one native issue without changing persisted workflow state."""
        self.work_item_service.close_work_item_issue(
            project_id=repository_scope, issue_iid=issue_number
        )
        self._records.record_issue_state(issue_number, is_open=False)

    def reopen_work_item_issue(self, *, repository_scope: str, issue_number: int) -> None:
        """Reopen one native issue without changing persisted workflow state."""
        self.work_item_service.reopen_work_item_issue(
            project_id=repository_scope, issue_iid=issue_number
        )
        self._records.record_issue_state(issue_number, is_open=True)

    def load_batch_inventory(self, *, repository_scope: str) -> FindingSyncInventory:
        """Load strict batch ownership without changing the legacy inventory path."""
        return load_batch_inventory(
            lambda is_open, labels: self._batch_records(repository_scope, is_open, labels)
        )

    def rediscover_batch(
        self, *, repository_scope: str, work_item_id: str
    ) -> tuple[FindingSyncRecord, ...]:
        """Rediscover an assigned batch ID across native issue states."""
        return rediscover_batch(
            work_item_id,
            lambda is_open, labels: self._batch_records(repository_scope, is_open, labels),
        )

    def read_work_item(self, *, repository_scope: str, issue_number: int) -> FindingSyncRecord:
        """Re-read exact native state rather than trusting an earlier snapshot."""
        lookup = self.work_item_service.lookup_service
        issue, is_open = lookup.client.get_issue(
            project_id=repository_scope, issue_iid=issue_number
        )
        state = lookup.parser.parse_work_item_state(issue.description)
        if state is None or state.source.repository_scope != repository_scope:
            raise ValueError("Cannot establish authoritative work-item state.")
        return self._record_from(
            GitLabWorkItemLookupResult(issue=issue, work_item=state, is_open=is_open)
        )

    def create_work_item(
        self, *, repository_scope: str, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Perform the authorized create exactly once; uncertain writes propagate."""
        upsert = self.work_item_service.upsert_service
        issue = upsert.client.create_issue(
            project_id=repository_scope,
            title=upsert.renderer.render_title(work_item),
            description=upsert.renderer.render_body(work_item),
            labels=upsert.renderer.render_labels(work_item),
        )
        return FindingSyncWriteResult(
            record=self._record_from(
                GitLabWorkItemLookupResult(
                    issue=issue,
                    work_item=WorkItemState.model_validate(
                        upsert.parser.parse_work_item_state(issue.description)
                    ),
                    is_open=True,
                )
            ),
            action="created",
        )

    def _batch_records(
        self, repository_scope: str, is_open: bool, labels: list[str]
    ) -> tuple[FindingSyncRecord, ...]:
        """Fail closed on malformed ownership; never silently skip indexed issues."""
        lookup = self.work_item_service.lookup_service
        listing = lookup.client.list_open_issues if is_open else lookup.client.list_closed_issues
        records = []
        for issue in listing(project_id=repository_scope, labels=labels):
            state = lookup.parser.parse_work_item_state(issue.description)
            if state is None or state.source.repository_scope != repository_scope:
                raise ValueError("Cannot establish complete batch ownership inventory.")
            records.append(
                self._record_from(
                    GitLabWorkItemLookupResult(issue=issue, work_item=state, is_open=is_open)
                )
            )
        return tuple(records)

    def _record_from(self, result: GitLabWorkItemLookupResult) -> FindingSyncRecord:
        """Retain the native snapshot behind its normalized record."""
        return self._records.remember(
            result,
            work_item=result.work_item,
            issue_number=result.issue.iid,
            issue_url=result.issue.web_url,
            is_open=result.is_open,
        )

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
