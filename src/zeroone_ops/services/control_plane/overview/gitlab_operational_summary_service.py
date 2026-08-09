"""Coordinate derived GitLab operational summary publication."""

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_builder import (
    GitLabOperationalSummaryBuilder,
)
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_renderer import (
    GitLabOperationalSummaryRenderer,
)
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_store import (
    GitLabOperationalSummaryStore,
)
from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    FindingSyncObservation,
)
from zeroone_ops.services.control_plane.overview.operational_summary_parser import (
    OperationalSummaryParser,
)
from zeroone_ops.services.control_plane.overview.operational_summary_service import (
    OperationalSummaryService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)


@dataclass(frozen=True)
class GitLabOperationalSummaryPublishResult:
    """Summarize one derived GitLab operational-summary publication."""

    issue: GitLabIssueInfo
    action: Literal["created", "updated", "unchanged"]


class GitLabOperationalSummaryService:
    """Publish a read-only GitLab operational summary when its view changes."""

    def __init__(
        self,
        *,
        store: GitLabOperationalSummaryStore,
        builder: GitLabOperationalSummaryBuilder | None = None,
        renderer: GitLabOperationalSummaryRenderer | None = None,
        parser: OperationalSummaryParser | None = None,
    ) -> None:
        """Initialize derived-summary composition over GitLab issue transport."""
        self.store = store
        self.builder = builder or GitLabOperationalSummaryBuilder()
        self.renderer = renderer or GitLabOperationalSummaryRenderer()
        self.parser = parser or OperationalSummaryParser()
        self.service = OperationalSummaryService(
            store=self.store,
            builder=self.builder,
            renderer=self.renderer,
            parser=self.parser,
        )

    def publish(
        self,
        *,
        project_id: str,
        work_items: list[GitLabWorkItemLookupResult],
        policy_issue_url: str | None,
        latest_finding_sync: FindingSyncObservation | None,
    ) -> GitLabOperationalSummaryPublishResult:
        """Create, update, or preserve the derived GitLab summary issue."""
        result = self.service.publish(
            scope_id=project_id,
            work_items=work_items,
            policy_issue_url=policy_issue_url,
            latest_finding_sync=latest_finding_sync,
        )
        return GitLabOperationalSummaryPublishResult(issue=result.issue, action=result.action)
