"""Provider-local GitHub work-item issue orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.services.control_plane.github_work_item_parser import GitHubWorkItemParser
from zeroone_ops.services.control_plane.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitHubWorkItemUpsertResult:
    """Summarize one authoritative GitHub work-item upsert."""

    issue: GitHubIssueInfo
    action: Literal["created", "updated", "unchanged"]
    work_item: WorkItemState


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
            rendered_work_item = work_item
            return GitHubWorkItemUpsertResult(
                issue=self.client.create_issue(
                    repository_id=repository_id,
                    title=title,
                    body=body,
                    labels=labels,
                ),
                action="created",
                work_item=rendered_work_item,
            )
        rendered_work_item = self._preserve_existing_work_item_id(
            existing_issue=existing_issue,
            work_item=work_item,
        )
        title = self.renderer.render_title(rendered_work_item)
        body = self.renderer.render_body(rendered_work_item)
        labels = self.renderer.render_labels(rendered_work_item)
        if existing_issue.title == title and existing_issue.body == body:
            return GitHubWorkItemUpsertResult(
                issue=existing_issue,
                action="unchanged",
                work_item=rendered_work_item,
            )
        return GitHubWorkItemUpsertResult(
            issue=self.client.update_issue(
                repository_id=repository_id,
                issue_number=existing_issue.number,
                title=title,
                body=body,
                labels=labels,
            ),
            action="updated",
            work_item=rendered_work_item,
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
            try:
                parsed = self.parser.parse_work_item_state(issue.body)
            except (GitHubClientError, ValidationError):
                LOGGER.warning(
                    "GitHub work-item issue scan skipped malformed machine state",
                    extra={
                        "issue_number": issue.number,
                        "issue_url": issue.web_url,
                    },
                    exc_info=True,
                )
                continue
            if parsed is None:
                continue
            if parsed.identity_key == work_item.identity_key:
                return issue
        return None

    def _preserve_existing_work_item_id(
        self,
        *,
        existing_issue: GitHubIssueInfo,
        work_item: WorkItemState,
    ) -> WorkItemState:
        """Return a work item that preserves the existing stable work-item ID when present."""
        parsed = self.parser.parse_work_item_state(existing_issue.body)
        if parsed is None:
            return work_item
        return work_item.model_copy(update={"work_item_id": parsed.work_item_id})
