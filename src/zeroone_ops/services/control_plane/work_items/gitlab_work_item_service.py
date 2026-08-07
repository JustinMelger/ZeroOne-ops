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
