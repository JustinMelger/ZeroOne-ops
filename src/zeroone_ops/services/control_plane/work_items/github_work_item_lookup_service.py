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
from zeroone_ops.services.control_plane.work_items.work_item_labels import (
    dismissed_work_item_query_labels,
    work_item_source_query_labels,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitHubWorkItemLookupResult:
    """Capture one matched authoritative work-item issue and its parsed state."""

    issue: GitHubIssueInfo
    work_item: WorkItemState
    is_open: bool = True


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
        for result in self._parse_work_items(
            self.client.list_open_issues(
                repository_id=repository_id,
                labels=work_item_source_query_labels(source.source),
            ),
            is_open=True,
        ):
            if result.work_item.kind != kind:
                continue
            if result.work_item.source == source:
                return result
        return None

    def find_open_work_item_by_change_request(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> GitHubWorkItemLookupResult | None:
        """Return the uniquely linked open remediation work item, when present."""
        matched_result: GitHubWorkItemLookupResult | None = None
        for result in self.list_open_work_items(repository_id=repository_id):
            if result.work_item.kind != "remediation":
                continue
            linked_change_request = result.work_item.linked_change_request
            if (
                linked_change_request is not None
                and linked_change_request.number == change_request_number
            ):
                if matched_result is not None:
                    LOGGER.warning(
                        "multiple GitHub remediation work items link to one change request; "
                        "review projection skipped",
                        extra={
                            "change_request_number": change_request_number,
                            "first_issue_number": matched_result.issue.number,
                            "duplicate_issue_number": result.issue.number,
                        },
                    )
                    return None
                matched_result = result
        return matched_result

    def list_open_work_items(
        self,
        *,
        repository_id: str,
    ) -> list[GitHubWorkItemLookupResult]:
        """Return all parseable open authoritative work items in one repository."""
        return self._parse_work_items(
            self.client.list_open_issues(
                repository_id=repository_id,
                labels=[self.renderer.AUTHORITATIVE_WORK_ITEM_LABEL],
            ),
            is_open=True,
        )

    def list_closed_work_items(
        self,
        *,
        repository_id: str,
    ) -> list[GitHubWorkItemLookupResult]:
        """Return all parseable closed authoritative work items in one repository."""
        return self._parse_work_items(
            self.client.list_closed_issues(
                repository_id=repository_id,
                labels=[self.renderer.AUTHORITATIVE_WORK_ITEM_LABEL],
            ),
            is_open=False,
        )

    def list_closed_dismissed_work_items_by_source(
        self,
        *,
        repository_id: str,
        kind: WorkItemKind,
        source: WorkItemSourceRef,
    ) -> list[GitHubWorkItemLookupResult]:
        """Return closed dismissed tombstones matching one stable identity."""
        return [
            result
            for result in self._parse_work_items(
                self.client.list_closed_issues(
                    repository_id=repository_id,
                    labels=dismissed_work_item_query_labels(),
                ),
                is_open=False,
            )
            if result.work_item.kind == kind
            and result.work_item.source == source
            and result.work_item.status == "dismissed"
        ]

    def _parse_work_items(
        self,
        issues: list[GitHubIssueInfo],
        *,
        is_open: bool,
    ) -> list[GitHubWorkItemLookupResult]:
        """Parse authoritative work-item machine state from listed issues."""
        results: list[GitHubWorkItemLookupResult] = []
        for issue in issues:
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
            results.append(
                GitHubWorkItemLookupResult(
                    issue=issue,
                    work_item=parsed,
                    is_open=is_open,
                )
            )
        return results
