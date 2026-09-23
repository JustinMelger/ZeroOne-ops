"""Coordinate provider callbacks for review-feedback projection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.review import PublishableReviewArtifact
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.review_projection import (
    review_feedback_projection_decision_service as decision_service_module,
)


@dataclass(frozen=True)
class ReviewFeedbackProjectionOutcome:
    """Return the provider-neutral result of one projection attempt."""

    action: str
    work_item: WorkItemState | None = None
    warning: str | None = None


class ReviewFeedbackProjectionCoordinator:
    """Apply shared projection decisions through provider-owned callbacks."""

    def __init__(
        self,
        decision_service: decision_service_module.ReviewFeedbackProjectionDecisionService
        | None = None,
    ) -> None:
        """Initialize the coordinator with the pure transition service."""
        self.decision_service = (
            decision_service or decision_service_module.ReviewFeedbackProjectionDecisionService()
        )

    def project(
        self,
        *,
        find_linked_work_item: Callable[[], WorkItemState | None],
        upsert_work_item: Callable[[WorkItemState], WorkItemState],
        change_request_state_lookup: Callable[[], ChangeRequestState] | None,
        reviewed_sha: str,
        artifact: PublishableReviewArtifact,
        review_note_url: str | None,
        review_note_reference: str | None,
    ) -> ReviewFeedbackProjectionOutcome:
        """Project one finalized artifact after optional current-head verification."""
        existing = find_linked_work_item()
        if existing is None:
            return ReviewFeedbackProjectionOutcome(action="no_linked_work_item")
        if change_request_state_lookup is not None:
            state = change_request_state_lookup()
            if state.state != "opened" or state.head_sha != reviewed_sha:
                return ReviewFeedbackProjectionOutcome(action="stale_review", work_item=existing)

        decision = self.decision_service.decide(
            work_item=existing,
            artifact=artifact,
            reviewed_sha=reviewed_sha,
            review_note_url=review_note_url,
            review_note_reference=review_note_reference,
        )
        if decision.action == "unchanged":
            return ReviewFeedbackProjectionOutcome(
                action="unchanged", work_item=existing, warning=decision.warning
            )
        return ReviewFeedbackProjectionOutcome(
            action="updated",
            work_item=upsert_work_item(decision.work_item),
            warning=decision.warning,
        )
