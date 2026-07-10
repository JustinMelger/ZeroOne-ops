"""Provider-local GitHub work-item issue orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.services.control_plane.github_work_item_parser import GitHubWorkItemParser
from zeroone_ops.services.control_plane.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)


@dataclass(frozen=True)
class GitHubWorkItemUpsertResult:
    """Summarize one authoritative GitHub work-item upsert."""

    issue: GitHubIssueInfo
    action: Literal["created", "updated", "unchanged"]


class GitHubWorkItemService:
    """Create, reuse, and update authoritative GitHub work-item issues."""

    def __init__(
        self,
        client: GitHubWorkItemClient,
        *,
        parser: GitHubWorkItemParser | None = None,
        renderer: GitHubWorkItemRenderer | None = None,
    ) -> None:
        """Initialize the GitHub work-item service."""
        self.client = client
        self.parser = parser or GitHubWorkItemParser()
        self.renderer = renderer or GitHubWorkItemRenderer()

    def upsert_work_item(
        self,
        *,
        repository_id: str,
        work_item: WorkItemState,
    ) -> GitHubWorkItemUpsertResult:
        """Create or update the authoritative open issue for one work item."""
        title = self.renderer.render_title(work_item)
        body = self.renderer.render_body(work_item)
        labels = self.renderer.render_labels(work_item)
        existing_issue = self._find_open_issue_by_identity(
            repository_id=repository_id,
            work_item=work_item,
        )
        if existing_issue is None:
            return GitHubWorkItemUpsertResult(
                issue=self.client.create_issue(
                    repository_id=repository_id,
                    title=title,
                    body=body,
                    labels=labels,
                ),
                action="created",
            )
        if existing_issue.title == title and existing_issue.body == body:
            return GitHubWorkItemUpsertResult(issue=existing_issue, action="unchanged")
        return GitHubWorkItemUpsertResult(
            issue=self.client.update_issue(
                repository_id=repository_id,
                issue_number=existing_issue.number,
                title=title,
                body=body,
                labels=labels,
            ),
            action="updated",
        )

    def _find_open_issue_by_identity(
        self,
        *,
        repository_id: str,
        work_item: WorkItemState,
    ) -> GitHubIssueInfo | None:
        """Return the matching open authoritative work-item issue when present."""
        for issue in self.client.list_open_issues(
            repository_id=repository_id,
            labels=["zeroone-work-item"],
        ):
            parsed = self.parser.parse_work_item_state(issue.body)
            if parsed is None:
                continue
            if parsed.identity_key == work_item.identity_key:
                return issue
        return None
