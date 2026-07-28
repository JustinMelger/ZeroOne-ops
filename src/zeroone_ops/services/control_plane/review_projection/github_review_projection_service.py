"""Provider-local projection of review status onto GitHub work items."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.review import ChangeRequestReviewContext, ReviewClassification
from zeroone_ops.models.work_item import ProjectedReviewState, WorkItemState
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)


@dataclass(frozen=True)
class GitHubReviewProjectionResult:
    """Summarize one GitHub review projection attempt."""

    action: str
    work_item: WorkItemState | None = None


class GitHubReviewProjectionService:
    """Project bounded review status onto existing authoritative GitHub work items."""

    def __init__(self, work_item_service: GitHubWorkItemService) -> None:
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
    ) -> GitHubReviewProjectionResult:
        """Project one published review onto an existing promoted remediation work item."""
        if review_note_url is None:
            return GitHubReviewProjectionResult(action="no_review_note")

        existing = self.work_item_service.find_open_work_item_by_change_request(
            repository_id=repository_id,
            change_request_number=context.change_request_number,
        )
        if existing is None:
            return GitHubReviewProjectionResult(action="no_linked_work_item")

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
            repository_id=repository_id,
            work_item=updated_work_item,
        )
        return GitHubReviewProjectionResult(
            action=upsert_result.action,
            work_item=upsert_result.work_item,
        )
