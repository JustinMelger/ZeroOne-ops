"""Facade over GitHub work-item lookup and upsert services."""

from __future__ import annotations

from zeroone_ops.models.work_item import WorkItemKind, WorkItemSourceRef, WorkItemState
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
    GitHubWorkItemLookupService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_parser import (
    GitHubWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_upsert_service import (
    GitHubWorkItemUpsertResult,
    GitHubWorkItemUpsertService,
)


class GitHubWorkItemService:
    """Compose authoritative GitHub work-item lookup and upsert behavior."""

    def __init__(
        self,
        client: GitHubWorkItemClient,
        *,
        parser: GitHubWorkItemParser | None = None,
        renderer: GitHubWorkItemRenderer | None = None,
    ) -> None:
        """Initialize the facade over lookup and upsert services."""
        parser = parser or GitHubWorkItemParser()
        renderer = renderer or GitHubWorkItemRenderer()
        self.lookup_service = GitHubWorkItemLookupService(
            client,
            parser=parser,
            renderer=renderer,
        )
        self.upsert_service = GitHubWorkItemUpsertService(
            client,
            lookup_service=self.lookup_service,
            parser=parser,
            renderer=renderer,
        )

    def upsert_work_item(
        self,
        *,
        repository_id: str,
        work_item: WorkItemState,
    ) -> GitHubWorkItemUpsertResult:
        """Create or update the authoritative open issue for one work item."""
        return self.upsert_service.upsert_work_item(
            repository_id=repository_id,
            work_item=work_item,
        )

    def find_open_work_item_by_source(
        self,
        *,
        repository_id: str,
        kind: WorkItemKind,
        source: WorkItemSourceRef,
    ) -> GitHubWorkItemLookupResult | None:
        """Return the matching open authoritative work item when present."""
        return self.lookup_service.find_open_work_item_by_source(
            repository_id=repository_id,
            kind=kind,
            source=source,
        )

    def close_work_item_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
    ) -> None:
        """Close one terminal authoritative work-item issue."""
        self.upsert_service.close_work_item_issue(
            repository_id=repository_id,
            issue_number=issue_number,
        )

    def reopen_work_item_issue(self, *, repository_id: str, issue_number: int) -> None:
        """Reopen one closed authoritative work-item issue."""
        self.upsert_service.client.reopen_issue(
            repository_id=repository_id,
            issue_number=issue_number,
        )

    def update_existing_work_item(
        self,
        *,
        repository_id: str,
        existing: GitHubWorkItemLookupResult,
        work_item: WorkItemState,
    ) -> GitHubWorkItemUpsertResult:
        """Update one already-identified authoritative work-item issue directly."""
        return self.upsert_service.update_existing_work_item(
            repository_id=repository_id,
            existing=existing,
            work_item=work_item,
        )

    def find_open_work_item_by_change_request(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> GitHubWorkItemLookupResult | None:
        """Return the work item authoritatively linked to one open change request."""
        return self.lookup_service.find_open_work_item_by_change_request(
            repository_id=repository_id,
            change_request_number=change_request_number,
        )

    def list_open_work_items(
        self,
        *,
        repository_id: str,
    ) -> list[GitHubWorkItemLookupResult]:
        """Return all parseable open authoritative work items in one repository."""
        return self.lookup_service.list_open_work_items(repository_id=repository_id)

    def list_closed_work_items(
        self,
        *,
        repository_id: str,
    ) -> list[GitHubWorkItemLookupResult]:
        """Return all parseable closed authoritative work items in one repository."""
        return self.lookup_service.list_closed_work_items(repository_id=repository_id)

    def list_closed_policy_deferred_work_items(
        self, *, repository_id: str
    ) -> list[GitHubWorkItemLookupResult]:
        """Return closed work items deferred by the current policy."""
        return self.lookup_service.list_closed_policy_deferred_work_items(
            repository_id=repository_id
        )
