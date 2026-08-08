"""Provider-local projection of review status onto GitLab work items."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.review import ChangeRequestReviewContext, ReviewClassification
from zeroone_ops.models.work_item import ProjectedReviewState, WorkItemState
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)


@dataclass(frozen=True)
class GitLabReviewProjectionResult:
    """Summarize one GitLab review projection attempt."""

    action: str
    work_item: WorkItemState | None = None


class GitLabReviewProjectionService:
    """Project bounded review status onto existing authoritative GitLab work items."""

    def __init__(self, work_item_service: GitLabWorkItemService) -> None:
        """Initialize the projection service."""
        self.work_item_service = work_item_service

    def project_review(
        self,
        *,
        repository_id: str,
        context: ChangeRequestReviewContext,
        classification: ReviewClassification,
        reviewed_sha: str,
        review_note_url: str | None,
    ) -> GitLabReviewProjectionResult:
        """Project one published review onto an existing remediation work item."""
        if review_note_url is None:
            return GitLabReviewProjectionResult(action="no_review_note")

        existing = self.work_item_service.find_open_work_item_by_change_request(
            project_id=repository_id,
            change_request_number=context.change_request_number,
        )
        if existing is None:
            return GitLabReviewProjectionResult(action="no_linked_work_item")

        updated_work_item = existing.work_item.model_copy(
            update={
                "projected_review": ProjectedReviewState(
                    classification=classification,
                    reviewed_sha=reviewed_sha,
                    review_note_url=review_note_url,
                    follow_up_required=classification != "no_findings",
                )
            }
        )
        upsert_result = self.work_item_service.upsert_work_item(
            project_id=repository_id,
            work_item=updated_work_item,
        )
        return GitLabReviewProjectionResult(
            action=upsert_result.action,
            work_item=upsert_result.work_item,
        )
