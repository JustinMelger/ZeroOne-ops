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
from zeroone_ops.services.control_plane.work_items.work_item_labels import (
    capacity_deferred_work_item_query_labels,
    dismissed_work_item_query_labels,
    policy_deferred_work_item_query_labels,
    work_item_source_query_labels,
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
        matches = self.list_open_work_items_by_source(
            project_id=project_id,
            kind=kind,
            source=source,
        )
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

    def find_open_work_item_by_change_request(
        self,
        *,
        project_id: str,
        change_request_number: int,
    ) -> GitLabWorkItemLookupResult | None:
        """Return the uniquely linked open remediation work item, when present."""
        matched_result: GitLabWorkItemLookupResult | None = None
        for result in self.list_open_work_items(project_id=project_id):
            if result.work_item.kind != "remediation":
                continue
            linked_change_request = result.work_item.linked_change_request
            if (
                linked_change_request is not None
                and linked_change_request.number == change_request_number
            ):
                if matched_result is not None:
                    LOGGER.warning(
                        "multiple GitLab remediation work items link to one change request; "
                        "review projection skipped",
                        extra={
                            "change_request_number": change_request_number,
                            "first_issue_iid": matched_result.issue.iid,
                            "duplicate_issue_iid": result.issue.iid,
                        },
                    )
                    return None
                matched_result = result
        return matched_result

    def list_open_work_items_by_source(
        self,
        *,
        project_id: str,
        kind: WorkItemKind,
        source: WorkItemSourceRef,
    ) -> list[GitLabWorkItemLookupResult]:
        """Return all open authoritative items matching one stable identity."""
        return [
            result
            for result in self._parse_work_items(
                self.client.list_open_issues(
                    project_id=project_id,
                    labels=work_item_source_query_labels(source.source),
                ),
                is_open=True,
            )
            if result.work_item.kind == kind and result.work_item.source == source
        ]

    def list_closed_dismissed_work_items_by_source(
        self,
        *,
        project_id: str,
        kind: WorkItemKind,
        source: WorkItemSourceRef,
    ) -> list[GitLabWorkItemLookupResult]:
        """Return closed dismissed tombstones matching one stable identity."""
        return [
            result
            for result in self._parse_work_items(
                self.client.list_closed_issues(
                    project_id=project_id,
                    labels=dismissed_work_item_query_labels(),
                ),
                is_open=False,
            )
            if (
                result.work_item.kind == kind
                and result.work_item.source == source
                and result.work_item.status == "dismissed"
            )
        ]

    def list_closed_policy_deferred_work_items(
        self, *, project_id: str
    ) -> list[GitLabWorkItemLookupResult]:
        """Return closed, reversibly deferred authoritative work items."""
        return [
            result
            for result in self._parse_work_items(
                self.client.list_closed_issues(
                    project_id=project_id,
                    labels=policy_deferred_work_item_query_labels(),
                ),
                is_open=False,
            )
            if result.work_item.status == "policy_deferred"
        ]

    def list_closed_capacity_deferred_work_items(
        self, *, project_id: str
    ) -> list[GitLabWorkItemLookupResult]:
        """Return closed work items deferred by active-capacity limits."""
        return [
            result
            for result in self._parse_work_items(
                self.client.list_closed_issues(
                    project_id=project_id,
                    labels=capacity_deferred_work_item_query_labels(),
                ),
                is_open=False,
            )
            if result.work_item.status == "capacity_deferred"
        ]

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
