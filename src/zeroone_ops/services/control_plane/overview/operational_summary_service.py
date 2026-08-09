"""Coordinate provider-local publication of shared operational summaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    FindingSyncObservation,
    OperationalSummaryView,
)
from zeroone_ops.services.control_plane.overview.operational_summary_parser import (
    OperationalSummaryParser,
)
from zeroone_ops.services.control_plane.overview.operational_summary_renderer import (
    OperationalSummaryRenderer,
)


class OperationalSummaryStore[IssueT](Protocol):
    """Provide provider-local storage for one derived summary issue."""

    def find_open_issue(self, *, scope_id: str) -> IssueT | None:
        """Return the one open summary issue for a provider scope."""
        ...

    def create_issue(self, *, scope_id: str, body: str) -> IssueT:
        """Create the one derived summary issue for a provider scope."""
        ...

    def update_issue_body(self, *, scope_id: str, issue: IssueT, body: str) -> IssueT:
        """Update one derived summary issue body."""
        ...

    def issue_body(self, issue: IssueT) -> str:
        """Return the provider-specific body field from an issue."""
        ...


class OperationalSummaryViewBuilder[WorkItemT](Protocol):
    """Build the shared view from provider-local or normalized work-item inputs."""

    def build(
        self,
        *,
        work_items: list[WorkItemT],
        policy_issue_url: str | None,
        latest_finding_sync: FindingSyncObservation | None,
    ) -> OperationalSummaryView:
        """Build one derived summary view."""
        ...


@dataclass(frozen=True)
class OperationalSummaryPublishResult[IssueT]:
    """Summarize one derived operational-summary publication."""

    issue: IssueT
    action: Literal["created", "updated", "unchanged"]


class OperationalSummaryService[IssueT, WorkItemT]:
    """Publish a derived summary while preserving its last valid observation."""

    def __init__(
        self,
        *,
        store: OperationalSummaryStore[IssueT],
        renderer: OperationalSummaryRenderer,
        builder: OperationalSummaryViewBuilder[WorkItemT],
        parser: OperationalSummaryParser | None = None,
    ) -> None:
        """Initialize shared summary publication with provider-local storage."""
        self.store = store
        self.renderer = renderer
        self.builder = builder
        self.parser = parser or OperationalSummaryParser()

    def publish(
        self,
        *,
        scope_id: str,
        work_items: list[WorkItemT],
        policy_issue_url: str | None,
        latest_finding_sync: FindingSyncObservation | None,
    ) -> OperationalSummaryPublishResult[IssueT]:
        """Create, update, or preserve the derived provider summary issue."""
        existing = self.store.find_open_issue(scope_id=scope_id)
        finding_sync = (
            self.parser.parse_latest_finding_sync(self.store.issue_body(existing))
            if existing is not None and latest_finding_sync is None
            else latest_finding_sync
        )
        body = self.renderer.render(
            self.builder.build(
                work_items=work_items,
                policy_issue_url=policy_issue_url,
                latest_finding_sync=finding_sync,
            )
        )
        if existing is None:
            return OperationalSummaryPublishResult(
                issue=self.store.create_issue(scope_id=scope_id, body=body),
                action="created",
            )
        if self.store.issue_body(existing) == body:
            return OperationalSummaryPublishResult(issue=existing, action="unchanged")
        return OperationalSummaryPublishResult(
            issue=self.store.update_issue_body(scope_id=scope_id, issue=existing, body=body),
            action="updated",
        )
