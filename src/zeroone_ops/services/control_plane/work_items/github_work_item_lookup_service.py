"""Lookup authoritative GitHub work-item issues by identity."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import WorkItemKind, WorkItemSourceRef, WorkItemState
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.services.control_plane.work_items.github_work_item_parser import (
    GitHubWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitHubWorkItemLookupResult:
    """Capture one matched authoritative work-item issue and its parsed state."""

    issue: GitHubIssueInfo
    work_item: WorkItemState


class GitHubWorkItemLookupService:
    """Find authoritative open GitHub work-item issues by source identity."""

    def __init__(
        self,
        client: GitHubWorkItemClient,
        *,
        parser: GitHubWorkItemParser | None = None,
        renderer: GitHubWorkItemRenderer | None = None,
    ) -> None:
        """Initialize the lookup service."""
        self.client = client
        self.parser = parser or GitHubWorkItemParser()
        self.renderer = renderer or GitHubWorkItemRenderer()

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
