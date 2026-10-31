"""GitHub transport adapter for normalized finding-sync operations."""

from zeroone_ops.models.finding_sync import (
    FindingSyncInventory,
    FindingSyncRecord,
    FindingSyncWriteResult,
)
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.work_items.finding_sync_inventory import (
    load_finding_sync_inventory,
    rediscover_batch,
    require_scoped_work_item,
)
from zeroone_ops.services.control_plane.work_items.finding_sync_record_store import (
    FindingSyncRecordStore,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_upsert_service import (
    GitHubWorkItemUpsertResult,
)


class GitHubFindingSyncStorage:
    """Translate normalized sync operations without deciding workflow policy."""

    def __init__(
        self, work_item_service: GitHubWorkItemService, *, policy_state: PolicyState | None = None
    ) -> None:
        """Retain transport and native snapshots without performing I/O."""
        self.work_item_service = work_item_service
        self.policy_state = policy_state
        self._records = FindingSyncRecordStore[GitHubWorkItemLookupResult]()

    def update_existing_work_item(
        self, *, repository_scope: str, existing: FindingSyncRecord, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Update using the native lookup corresponding to the supplied snapshot."""
        result = self.work_item_service.update_existing_work_item(
            repository_id=repository_scope,
            existing=self._records.native_record(existing),
            work_item=work_item,
            policy_state=self.policy_state,
        )
        return self._write_result(result, is_open=self._records.projected_is_open(existing))

    def close_work_item_issue(self, *, repository_scope: str, issue_number: int) -> None:
        """Close one native issue without changing persisted workflow state."""
        self.work_item_service.close_work_item_issue(
            repository_id=repository_scope, issue_number=issue_number
        )
        self._records.record_issue_state(issue_number, is_open=False)

    def reopen_work_item_issue(self, *, repository_scope: str, issue_number: int) -> None:
        """Reopen one native issue without changing persisted workflow state."""
        self.work_item_service.reopen_work_item_issue(
            repository_id=repository_scope, issue_number=issue_number
        )
        self._records.record_issue_state(issue_number, is_open=True)

    def load_inventory(self, *, repository_scope: str) -> FindingSyncInventory:
        """Load strict ownership for singles and batches through indexed discovery."""
        return load_finding_sync_inventory(
            lambda is_open, labels: self._list_records(repository_scope, is_open, labels)
        )

    def rediscover_batch(
        self, *, repository_scope: str, work_item_id: str
    ) -> tuple[FindingSyncRecord, ...]:
        """Rediscover an assigned batch ID across native issue states."""
        return rediscover_batch(
            work_item_id,
            lambda is_open, labels: self._list_records(repository_scope, is_open, labels),
        )

    def read_work_item(self, *, repository_scope: str, issue_number: int) -> FindingSyncRecord:
        """Re-read exact native state rather than trusting an earlier snapshot."""
        lookup = self.work_item_service.lookup_service
        issue, is_open = lookup.client.get_issue(
            repository_id=repository_scope, issue_number=issue_number
        )
        state = require_scoped_work_item(
            lookup.parser.parse_work_item_state(issue.body),
            repository_scope=repository_scope,
            error_message="Cannot establish authoritative work-item state.",
        )
        return self._record_from(
            GitHubWorkItemLookupResult(issue=issue, work_item=state, is_open=is_open)
        )

    def validate_work_item_projection(self, work_item: WorkItemState) -> None:
        """Reject oversized complete bodies before issuing a provider request."""
        self.work_item_service.upsert_service.renderer.render_body(
            work_item, policy=self.policy_state
        )

    def create_work_item(
        self, *, repository_scope: str, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Perform the authorized create exactly once; uncertain writes propagate."""
        upsert = self.work_item_service.upsert_service
        issue = upsert.client.create_issue(
            repository_id=repository_scope,
            title=upsert.renderer.render_title(work_item),
            body=upsert.renderer.render_body(work_item, policy=self.policy_state),
            labels=upsert.renderer.render_labels(work_item),
        )
        return FindingSyncWriteResult(
            record=self._record_from(
                GitHubWorkItemLookupResult(
                    issue=issue,
                    work_item=WorkItemState.model_validate(
                        upsert.parser.parse_work_item_state(issue.body)
                    ),
                    is_open=True,
                )
            ),
            action="created",
        )

    def _list_records(
        self, repository_scope: str, is_open: bool, labels: list[str]
    ) -> tuple[FindingSyncRecord, ...]:
        """Fail closed on malformed ownership; never silently skip indexed issues."""
        lookup = self.work_item_service.lookup_service
        listing = lookup.client.list_open_issues if is_open else lookup.client.list_closed_issues
        records = []
        for issue in listing(repository_id=repository_scope, labels=labels):
            state = require_scoped_work_item(
                lookup.parser.parse_work_item_state(issue.body),
                repository_scope=repository_scope,
                error_message="Cannot establish complete batch ownership inventory.",
            )
            records.append(
                self._record_from(
                    GitHubWorkItemLookupResult(issue=issue, work_item=state, is_open=is_open)
                )
            )
        return tuple(records)

    def _record_from(self, result: GitHubWorkItemLookupResult) -> FindingSyncRecord:
        """Retain the native snapshot behind its normalized record."""
        return self._records.remember(
            result,
            work_item=result.work_item,
            issue_number=result.issue.number,
            issue_url=result.issue.web_url,
            is_open=result.is_open,
        )

    def _write_result(
        self, result: GitHubWorkItemUpsertResult, *, is_open: bool
    ) -> FindingSyncWriteResult:
        """Normalize the actual state and issue returned by persistence."""
        record = self._record_from(
            GitHubWorkItemLookupResult(
                issue=result.issue,
                work_item=result.work_item,
                is_open=is_open,
            )
        )
        return FindingSyncWriteResult(record=record, action=result.action)
