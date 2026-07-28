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
