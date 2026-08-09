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
from zeroone_ops.services.control_plane.overview.operational_summary_service import (
    OperationalSummaryService,
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
        self.service = OperationalSummaryService(
            store=_GitHubOperationalSummaryStoreAdapter(self.store),
            builder=self.builder,
            renderer=self.renderer,
            parser=self.parser,
        )

    def publish(
        self,
        *,
        repository_id: str,
        work_items: list[GitHubWorkItemLookupResult],
        policy_issue_url: str | None,
        latest_finding_sync: GitHubFindingSyncObservation | None,
    ) -> GitHubOperationalSummaryPublishResult:
        """Create, update, or preserve the derived summary issue."""
        result = self.service.publish(
            scope_id=repository_id,
            work_items=work_items,
            policy_issue_url=policy_issue_url,
            latest_finding_sync=latest_finding_sync,
        )
        return GitHubOperationalSummaryPublishResult(issue=result.issue, action=result.action)


class _GitHubOperationalSummaryStoreAdapter:
    """Adapt the established GitHub store signature to shared summary storage."""

    def __init__(self, store: GitHubOperationalSummaryStore) -> None:
        """Initialize one provider-contract adapter."""
        self.store = store

    def find_open_issue(self, *, scope_id: str) -> GitHubIssueInfo | None:
        """Find the GitHub summary using its repository identifier."""
        return self.store.find_open_issue(repository_id=scope_id)

    def create_issue(self, *, scope_id: str, body: str) -> GitHubIssueInfo:
        """Create the GitHub summary using its repository identifier."""
        return self.store.create_issue(repository_id=scope_id, body=body)

    def update_issue_body(
        self,
        *,
        scope_id: str,
        issue: GitHubIssueInfo,
        body: str,
    ) -> GitHubIssueInfo:
        """Update the GitHub summary body through its existing store contract."""
        return self.store.update_issue_body(
            repository_id=scope_id,
            issue_number=issue.number,
            body=body,
        )

    def issue_body(self, issue: GitHubIssueInfo) -> str:
        """Return the GitHub summary body for persisted-observation parsing."""
        return issue.body
