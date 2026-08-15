"""Facade over GitLab work-item lookup and upsert services."""

from zeroone_ops.models.work_item import WorkItemKind, WorkItemSourceRef, WorkItemState
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
    GitLabWorkItemLookupService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_parser import (
    GitLabWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_renderer import (
    GitLabWorkItemRenderer,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_upsert_service import (
    GitLabWorkItemUpsertResult,
    GitLabWorkItemUpsertService,
)


class GitLabWorkItemService:
    """Compose authoritative GitLab work-item lookup and upsert behavior."""

    def __init__(self, client: GitLabWorkItemClient) -> None:
        """Initialize the GitLab work-item facade."""
        parser = GitLabWorkItemParser()
        renderer = GitLabWorkItemRenderer()
        self.lookup_service = GitLabWorkItemLookupService(
            client,
            parser=parser,
            renderer=renderer,
        )
        self.upsert_service = GitLabWorkItemUpsertService(
            client,
            lookup_service=self.lookup_service,
            parser=parser,
            renderer=renderer,
        )

    def upsert_work_item(
        self, *, project_id: str, work_item: WorkItemState
    ) -> GitLabWorkItemUpsertResult:
        """Create or update one authoritative open GitLab work-item issue."""
        return self.upsert_service.upsert_work_item(project_id=project_id, work_item=work_item)

    def find_open_work_item_by_source(
        self, *, project_id: str, kind: WorkItemKind, source: WorkItemSourceRef
    ) -> GitLabWorkItemLookupResult | None:
        """Return the matching open authoritative work item, when present."""
        return self.lookup_service.find_open_work_item_by_source(
            project_id=project_id,
            kind=kind,
            source=source,
        )

    def close_work_item_issue(self, *, project_id: str, issue_iid: int) -> None:
        """Close one terminal authoritative GitLab work-item issue."""
        self.upsert_service.close_work_item_issue(
            project_id=project_id,
            issue_iid=issue_iid,
        )

    def reopen_work_item_issue(self, *, project_id: str, issue_iid: int) -> None:
        """Reopen one closed authoritative work-item issue."""
        self.upsert_service.client.reopen_issue(project_id=project_id, issue_iid=issue_iid)

    def update_existing_work_item(
        self,
        *,
        project_id: str,
        existing: GitLabWorkItemLookupResult,
        work_item: WorkItemState,
    ) -> GitLabWorkItemUpsertResult:
        """Update one already-identified authoritative work-item issue directly."""
        return self.upsert_service.update_existing_work_item(
            project_id=project_id,
            existing=existing,
            work_item=work_item,
        )

    def find_open_work_item_by_change_request(
        self,
        *,
        project_id: str,
        change_request_number: int,
    ) -> GitLabWorkItemLookupResult | None:
        """Return the uniquely linked open remediation work item, when present."""
        return self.lookup_service.find_open_work_item_by_change_request(
            project_id=project_id,
            change_request_number=change_request_number,
        )

    def list_open_work_items(self, *, project_id: str) -> list[GitLabWorkItemLookupResult]:
        """Return every parseable open authoritative GitLab work item."""
        return self.lookup_service.list_open_work_items(project_id=project_id)

    def list_closed_work_items(self, *, project_id: str) -> list[GitLabWorkItemLookupResult]:
        """Return every parseable closed authoritative GitLab work item."""
        return self.lookup_service.list_closed_work_items(project_id=project_id)

    def list_closed_policy_deferred_work_items(
        self, *, project_id: str
    ) -> list[GitLabWorkItemLookupResult]:
        """Return closed work items deferred by the current policy."""
        return self.lookup_service.list_closed_policy_deferred_work_items(project_id=project_id)

    def list_closed_capacity_deferred_work_items(
        self, *, project_id: str
    ) -> list[GitLabWorkItemLookupResult]:
        """Return closed work items deferred by active capacity."""
        return self.lookup_service.list_closed_capacity_deferred_work_items(project_id=project_id)
