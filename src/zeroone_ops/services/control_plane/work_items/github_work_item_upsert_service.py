"""Upsert authoritative GitHub work-item issues."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
    GitHubWorkItemLookupService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_parser import (
    GitHubWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)


@dataclass(frozen=True)
class GitHubWorkItemUpsertResult:
    """Summarize one authoritative GitHub work-item upsert."""

    issue: GitHubIssueInfo
    action: Literal["created", "updated", "unchanged"]
    work_item: WorkItemState


class GitHubWorkItemUpsertService:
    """Create or update authoritative open GitHub work-item issues."""

    def __init__(
        self,
        client: GitHubWorkItemClient,
        *,
        lookup_service: GitHubWorkItemLookupService,
        parser: GitHubWorkItemParser | None = None,
        renderer: GitHubWorkItemRenderer | None = None,
    ) -> None:
        """Initialize the upsert service."""
        self.client = client
        self.lookup_service = lookup_service
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
        existing = self.lookup_service.find_open_work_item_by_source(
            repository_id=repository_id,
            kind=work_item.kind,
            source=work_item.source,
        )
        if existing is None:
            return GitHubWorkItemUpsertResult(
                issue=self.client.create_issue(
                    repository_id=repository_id,
                    title=title,
                    body=body,
                    labels=labels,
                ),
                action="created",
                work_item=work_item,
            )
        rendered_work_item = self._merge_existing_authoritative_state(
            existing_issue=existing.issue,
            work_item=work_item,
        )
        title = self.renderer.render_title(rendered_work_item)
        body = self.renderer.render_body(rendered_work_item)
        labels = self.renderer.render_labels(rendered_work_item)
        if existing.issue.title == title and existing.issue.body == body:
            return GitHubWorkItemUpsertResult(
                issue=existing.issue,
                action="unchanged",
                work_item=rendered_work_item,
            )
        return GitHubWorkItemUpsertResult(
            issue=self.client.update_issue(
                repository_id=repository_id,
                issue_number=existing.issue.number,
                title=title,
                body=body,
                labels=labels,
            ),
            action="updated",
            work_item=rendered_work_item,
        )

    def close_work_item_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
    ) -> None:
        """Close one terminal authoritative work-item issue."""
        self.client.close_issue(
            repository_id=repository_id,
            issue_number=issue_number,
        )

    def update_existing_work_item(
        self,
        *,
        repository_id: str,
        existing: GitHubWorkItemLookupResult,
        work_item: WorkItemState,
    ) -> GitHubWorkItemUpsertResult:
        """Update one already-identified authoritative work-item issue directly."""
        if existing.work_item.identity_key != work_item.identity_key:
            raise ValueError("Recovery update must preserve authoritative work-item identity.")
        title = self.renderer.render_title(work_item)
        body = self.renderer.render_body(work_item)
        labels = self.renderer.render_labels(work_item)
        if existing.issue.title == title and existing.issue.body == body:
            return GitHubWorkItemUpsertResult(
                issue=existing.issue,
                action="unchanged",
                work_item=work_item,
            )
        return GitHubWorkItemUpsertResult(
            issue=self.client.update_issue(
                repository_id=repository_id,
                issue_number=existing.issue.number,
                title=title,
                body=body,
                labels=labels,
            ),
            action="updated",
            work_item=work_item,
        )

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
        if (
            "publication_retry" not in work_item.model_fields_set
            and work_item.publication_retry is None
            and parsed.publication_retry is not None
        ):
            update["publication_retry"] = parsed.publication_retry
        if (
            "execution_failure" not in work_item.model_fields_set
            and work_item.execution_failure is None
            and parsed.execution_failure is not None
        ):
            update["execution_failure"] = parsed.execution_failure
        if "attempt_number" not in work_item.model_fields_set:
            update["attempt_number"] = parsed.attempt_number
        if "recovery_events" not in work_item.model_fields_set:
            update["recovery_events"] = parsed.recovery_events
        if (
            "resolution" not in work_item.model_fields_set
            and work_item.resolution is None
            and parsed.resolution is not None
        ):
            update["resolution"] = parsed.resolution
        return work_item.model_copy(update=update)
