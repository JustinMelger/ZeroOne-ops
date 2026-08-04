"""Coordinate derived GitHub operational summary publication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.services.control_plane.overview.github_operational_summary_builder import (
    GitHubOperationalSummaryBuilder,
)
from zeroone_ops.services.control_plane.overview.github_operational_summary_parser import (
    GitHubOperationalSummaryParser,
)
from zeroone_ops.services.control_plane.overview.github_operational_summary_renderer import (
    GitHubFindingSyncObservation,
    GitHubOperationalSummaryRenderer,
)
from zeroone_ops.services.control_plane.overview.github_operational_summary_store import (
    GitHubOperationalSummaryStore,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)


@dataclass(frozen=True)
class GitHubOperationalSummaryPublishResult:
    """Summarize one derived operational-summary publication."""

    issue: GitHubIssueInfo
    action: Literal["created", "updated", "unchanged"]


class GitHubOperationalSummaryService:
    """Publish a read-only GitHub operational summary when its view changes."""

    def __init__(
        self,
        *,
        store: GitHubOperationalSummaryStore,
        builder: GitHubOperationalSummaryBuilder | None = None,
        renderer: GitHubOperationalSummaryRenderer | None = None,
        parser: GitHubOperationalSummaryParser | None = None,
    ) -> None:
        """Initialize derived-summary composition over provider-local components."""
        self.store = store
        self.builder = builder or GitHubOperationalSummaryBuilder()
        self.renderer = renderer or GitHubOperationalSummaryRenderer()
        self.parser = parser or GitHubOperationalSummaryParser()

    def publish(
        self,
        *,
        repository_id: str,
        work_items: list[GitHubWorkItemLookupResult],
        policy_issue_url: str | None,
        latest_finding_sync: GitHubFindingSyncObservation | None,
    ) -> GitHubOperationalSummaryPublishResult:
        """Create, update, or preserve the derived summary issue."""
        existing = self.store.find_open_issue(repository_id=repository_id)
        persisted_finding_sync = (
            self.parser.parse_latest_finding_sync(existing.body)
            if existing is not None and latest_finding_sync is None
            else latest_finding_sync
        )
        body = self.renderer.render(
            self.builder.build(
                work_items=work_items,
                policy_issue_url=policy_issue_url,
                latest_finding_sync=persisted_finding_sync,
            )
        )
        if existing is None:
            return GitHubOperationalSummaryPublishResult(
                issue=self.store.create_issue(repository_id=repository_id, body=body),
                action="created",
            )
        if existing.body == body:
            return GitHubOperationalSummaryPublishResult(issue=existing, action="unchanged")
        return GitHubOperationalSummaryPublishResult(
            issue=self.store.update_issue_body(
                repository_id=repository_id,
                issue_number=existing.number,
                body=body,
            ),
            action="updated",
        )
