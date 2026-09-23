"""Provider-local projection of review status onto GitLab work items."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.review import (
    ChangeRequestReviewContext,
    PublishableReviewArtifact,
    ReviewClassification,
)
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.review_projection import (
    review_feedback_projection_coordinator as coordinator_module,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)


@dataclass(frozen=True)
class GitLabReviewProjectionResult:
    """Summarize one GitLab review projection attempt."""

    action: str
    work_item: WorkItemState | None = None
    warning: str | None = None


class GitLabReviewProjectionService:
    """Project bounded review status onto existing authoritative GitLab work items."""

    def __init__(
        self,
        work_item_service: GitLabWorkItemService,
        change_request_state_lookup: Callable[[int], ChangeRequestState] | None = None,
    ) -> None:
        """Initialize the projection service."""
        self.work_item_service = work_item_service
        self.change_request_state_lookup = change_request_state_lookup
        self.coordinator = coordinator_module.ReviewFeedbackProjectionCoordinator()

    def project_review(
        self,
        *,
        repository_id: str,
        context: ChangeRequestReviewContext,
        reviewed_sha: str,
        artifact: PublishableReviewArtifact | None = None,
        classification: ReviewClassification | None = None,
        review_note_id: int | None = None,
        review_note_url: str | None = None,
    ) -> GitLabReviewProjectionResult:
        """Project one published review onto an existing remediation work item."""
        if review_note_id is None and review_note_url is None:
            return GitLabReviewProjectionResult(action="no_review_note")

        artifact = artifact or PublishableReviewArtifact(
            classification=classification or "manual_review_only",
            summary="Previously published review projection.",
        )
        state_lookup = self.change_request_state_lookup
        outcome = self.coordinator.project(
            find_linked_work_item=lambda: _find_linked_work_item(
                self.work_item_service,
                project_id=repository_id,
                change_request_number=context.change_request_number,
            ),
            upsert_work_item=lambda work_item: (
                self.work_item_service.upsert_work_item(
                    project_id=repository_id,
                    work_item=work_item,
                ).work_item
            ),
            change_request_state_lookup=(
                None
                if state_lookup is None
                else lambda: state_lookup(context.change_request_number)
            ),
            artifact=artifact,
            reviewed_sha=reviewed_sha,
            review_note_url=review_note_url,
            review_note_reference=(
                f"gitlab-note-{review_note_id}" if review_note_id is not None else review_note_url
            ),
        )
        return GitLabReviewProjectionResult(
            action=outcome.action, work_item=outcome.work_item, warning=outcome.warning
        )


def _find_linked_work_item(
    work_item_service: GitLabWorkItemService,
    *,
    project_id: str,
    change_request_number: int,
) -> WorkItemState | None:
    """Adapt GitLab's lookup result to the shared coordinator input."""
    result = work_item_service.find_open_work_item_by_change_request(
        project_id=project_id,
        change_request_number=change_request_number,
    )
    return result.work_item if result is not None else None
