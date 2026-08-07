"""Lookup authoritative GitLab work-item issues by identity."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.work_item import WorkItemKind, WorkItemSourceRef, WorkItemState
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_parser import (
    GitLabWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_renderer import (
    GitLabWorkItemRenderer,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitLabWorkItemLookupResult:
    """Capture one authoritative GitLab work-item issue and parsed state."""

    issue: GitLabIssueInfo
    work_item: WorkItemState
    is_open: bool = True


class GitLabWorkItemLookupService:
    """Find authoritative GitLab work-item issues by stable identity."""

    def __init__(
        self,
        client: GitLabWorkItemClient,
        *,
        parser: GitLabWorkItemParser | None = None,
        renderer: GitLabWorkItemRenderer | None = None,
    ) -> None:
        """Initialize the GitLab work-item lookup service."""
        self.client = client
        self.parser = parser or GitLabWorkItemParser()
        self.renderer = renderer or GitLabWorkItemRenderer()

    def find_open_work_item_by_source(
        self,
        *,
        project_id: str,
        kind: WorkItemKind,
        source: WorkItemSourceRef,
    ) -> GitLabWorkItemLookupResult | None:
        """Return the uniquely matching open authoritative work item, if any."""
        matches = [
            result
            for result in self.list_open_work_items(project_id=project_id)
            if result.work_item.kind == kind and result.work_item.source == source
        ]
        if len(matches) <= 1:
            return matches[0] if matches else None
        LOGGER.warning(
            "multiple GitLab work items share one authoritative identity; reuse skipped",
            extra={
                "project_id": project_id,
                "source": source.source,
                "source_item_key": source.source_item_key,
                "issue_iids": [result.issue.iid for result in matches],
            },
        )
        return None

    def list_open_work_items(self, *, project_id: str) -> list[GitLabWorkItemLookupResult]:
        """Return all parseable open authoritative work items in one project."""
        return self._parse_work_items(
            self.client.list_open_issues(
                project_id=project_id,
                labels=[self.renderer.AUTHORITATIVE_WORK_ITEM_LABEL],
            ),
            is_open=True,
        )

    def list_closed_work_items(self, *, project_id: str) -> list[GitLabWorkItemLookupResult]:
        """Return all parseable closed authoritative work items in one project."""
        return self._parse_work_items(
            self.client.list_closed_issues(
                project_id=project_id,
                labels=[self.renderer.AUTHORITATIVE_WORK_ITEM_LABEL],
            ),
            is_open=False,
        )

    def _parse_work_items(
        self,
        issues: list[GitLabIssueInfo],
        *,
        is_open: bool,
    ) -> list[GitLabWorkItemLookupResult]:
        """Parse authoritative work-item state independently for each issue."""
        results: list[GitLabWorkItemLookupResult] = []
        for issue in issues:
            try:
                parsed = self.parser.parse_work_item_state(issue.description)
            except (GitLabClientError, ValidationError):
                LOGGER.warning(
                    "GitLab work-item issue scan skipped malformed machine state",
                    extra={"issue_iid": issue.iid, "issue_url": issue.web_url},
                    exc_info=True,
                )
                continue
            if parsed is not None:
                results.append(
                    GitLabWorkItemLookupResult(
                        issue=issue,
                        work_item=parsed,
                        is_open=is_open,
                    )
                )
        return results
