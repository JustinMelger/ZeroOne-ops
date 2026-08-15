"""Upsert authoritative GitLab work-item issues."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
    GitLabWorkItemLookupService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_parser import (
    GitLabWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_renderer import (
    GitLabWorkItemRenderer,
)


@dataclass(frozen=True)
class GitLabWorkItemUpsertResult:
    """Summarize one authoritative GitLab work-item upsert."""

    issue: GitLabIssueInfo
    action: Literal["created", "updated", "unchanged", "suppressed"]
    work_item: WorkItemState


class GitLabWorkItemUpsertService:
    """Create or update authoritative open GitLab work-item issues."""

    def __init__(
        self,
        client: GitLabWorkItemClient,
        *,
        lookup_service: GitLabWorkItemLookupService,
        parser: GitLabWorkItemParser | None = None,
        renderer: GitLabWorkItemRenderer | None = None,
    ) -> None:
        """Initialize the GitLab work-item upsert service."""
        self.client = client
        self.lookup_service = lookup_service
        self.parser = parser or GitLabWorkItemParser()
        self.renderer = renderer or GitLabWorkItemRenderer()

    def upsert_work_item(
        self,
        *,
        project_id: str,
        work_item: WorkItemState,
    ) -> GitLabWorkItemUpsertResult:
        """Create or update the authoritative open issue for one work item."""
        matches = self.lookup_service.list_open_work_items_by_source(
            project_id=project_id,
            kind=work_item.kind,
            source=work_item.source,
        )
        if len(matches) > 1:
            raise ValueError("Cannot upsert an ambiguously matched authoritative work item.")
        if matches:
            existing = matches[0]
            rendered_work_item = self._merge_existing_authoritative_state(existing, work_item)
            return self.update_existing_work_item(
                project_id=project_id,
                existing=existing,
                work_item=rendered_work_item,
            )
        dismissed_matches = self.lookup_service.list_closed_dismissed_work_items_by_source(
            project_id=project_id,
            kind=work_item.kind,
            source=work_item.source,
        )
        if len(dismissed_matches) > 1:
            raise ValueError("Cannot upsert an ambiguously matched dismissed work item.")
        if dismissed_matches:
            dismissed = dismissed_matches[0]
            return GitLabWorkItemUpsertResult(
                issue=dismissed.issue,
                action="suppressed",
                work_item=dismissed.work_item,
            )
        if not matches:
            return self._create(project_id=project_id, work_item=work_item)
        raise AssertionError("Open work-item matches were handled before creation.")

    def update_existing_work_item(
        self,
        *,
        project_id: str,
        existing: GitLabWorkItemLookupResult,
        work_item: WorkItemState,
    ) -> GitLabWorkItemUpsertResult:
        """Update one already-identified authoritative work-item issue directly."""
        if existing.work_item.identity_key != work_item.identity_key:
            raise ValueError("Recovery update must preserve authoritative work-item identity.")
        title = self.renderer.render_title(work_item)
        description = self.renderer.render_body(work_item)
        labels = self.renderer.render_labels(work_item)
        if (
            existing.issue.title == title
            and existing.issue.description == description
            and existing.issue.labels == labels
        ):
            return GitLabWorkItemUpsertResult(
                issue=existing.issue,
                action="unchanged",
                work_item=work_item,
            )
        return GitLabWorkItemUpsertResult(
            issue=self.client.update_issue(
                project_id=project_id,
                issue_iid=existing.issue.iid,
                title=title,
                description=description,
                labels=labels,
            ),
            action="updated",
            work_item=work_item,
        )

    def close_work_item_issue(self, *, project_id: str, issue_iid: int) -> None:
        """Close one terminal authoritative work-item issue."""
        self.client.close_issue(project_id=project_id, issue_iid=issue_iid)

    def _create(
        self,
        *,
        project_id: str,
        work_item: WorkItemState,
    ) -> GitLabWorkItemUpsertResult:
        """Create one newly promoted authoritative work-item issue."""
        return GitLabWorkItemUpsertResult(
            issue=self.client.create_issue(
                project_id=project_id,
                title=self.renderer.render_title(work_item),
                description=self.renderer.render_body(work_item),
                labels=self.renderer.render_labels(work_item),
            ),
            action="created",
            work_item=work_item,
        )

    def _merge_existing_authoritative_state(
        self,
        existing: GitLabWorkItemLookupResult,
        work_item: WorkItemState,
    ) -> WorkItemState:
        """Preserve existing authoritative fields when the new item omits them."""
        parsed = self.parser.parse_work_item_state(existing.issue.description)
        if parsed is None:
            return work_item
        update: dict[str, object] = {"work_item_id": parsed.work_item_id}
        for field_name in (
            "linked_change_request",
            "projected_review",
            "publication_retry",
            "execution_failure",
            "policy_deferral",
            "capacity_deferral",
            "resolution",
        ):
            existing_value = getattr(parsed, field_name)
            if field_name not in work_item.model_fields_set and existing_value is not None:
                update[field_name] = existing_value
        if "attempt_number" not in work_item.model_fields_set:
            update["attempt_number"] = parsed.attempt_number
        if "recovery_events" not in work_item.model_fields_set:
            update["recovery_events"] = parsed.recovery_events
        return work_item.model_copy(update=update)
