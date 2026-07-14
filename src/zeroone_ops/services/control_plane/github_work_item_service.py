"""Provider-local GitHub work-item issue orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import WorkItemKind, WorkItemSourceRef, WorkItemState
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


@dataclass(frozen=True)
class GitHubWorkItemLookupResult:
    """Capture one matched authoritative work-item issue and its parsed state."""

    issue: GitHubIssueInfo
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
        rendered_work_item = self._merge_existing_authoritative_state(
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

    def find_open_work_item_by_source(
        self,
        *,
        repository_id: str,
        kind: WorkItemKind,
        source: WorkItemSourceRef,
    ) -> GitHubWorkItemLookupResult | None:
        """Return the matching open authoritative work item when present."""
        authoritative_label = self.renderer.AUTHORITATIVE_WORK_ITEM_LABEL
        for issue in self.client.list_open_issues(
            repository_id=repository_id,
            labels=[authoritative_label],
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
            if parsed.kind != kind:
                continue
            if parsed.source == source:
                return GitHubWorkItemLookupResult(issue=issue, work_item=parsed)
        return None

    def _find_open_issue_by_identity(
        self,
        *,
        repository_id: str,
        work_item: WorkItemState,
    ) -> GitHubIssueInfo | None:
        """Return the matching open authoritative work-item issue when present."""
        lookup_result = self.find_open_work_item_by_source(
            repository_id=repository_id,
            kind=work_item.kind,
            source=work_item.source,
        )
        return None if lookup_result is None else lookup_result.issue

    def _merge_existing_authoritative_state(
        self,
        *,
        existing_issue: GitHubIssueInfo,
        work_item: WorkItemState,
    ) -> WorkItemState:
        """Return a work item that preserves authoritative existing state when needed."""
        parsed = self.parser.parse_work_item_state(existing_issue.body)
        if parsed is None:
            return work_item
        update: dict[str, object] = {"work_item_id": parsed.work_item_id}
        if (
            "linked_change_request" not in work_item.model_fields_set
            and work_item.linked_change_request is None
            and parsed.linked_change_request is not None
        ):
            update["linked_change_request"] = parsed.linked_change_request
        if (
            "projected_review" not in work_item.model_fields_set
            and work_item.projected_review is None
            and parsed.projected_review is not None
        ):
            update["projected_review"] = parsed.projected_review
        return work_item.model_copy(update=update)
