"""Apply operator-approved remediation review-feedback decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from zeroone_ops.models.work_item import ReviewRevisionRequest, WorkItemState
from zeroone_ops.services.remediation.recovery.recovery_decision_service import (
    RecoveryDecisionService,
)


@dataclass(frozen=True)
class ReviewFeedbackRequest:
    """Represent one authorized requeue request against projected review evidence."""

    actor: str
    request_reference: str
    expected_state_fingerprint: str
    occurred_at: datetime


@dataclass(frozen=True)
class ReviewFeedbackDecision:
    """Return one accepted review-feedback transition or a stable rejection."""

    accepted: bool
    message: str
    work_item: WorkItemState


class ReviewFeedbackDecisionService:
    """Queue one bounded same-branch revision without provider dependencies."""

    def decide(
        self,
        *,
        work_item: WorkItemState,
        request: ReviewFeedbackRequest,
    ) -> ReviewFeedbackDecision:
        """Accept requeue only for actionable feedback awaiting an operator."""
        if work_item.kind != "remediation":
            return self._reject(
                work_item,
                "Review feedback is available only for remediation work.",
            )
        if work_item.status != "review_feedback_required":
            return self._reject(
                work_item,
                "Review feedback can be requeued only while action is required.",
            )
        projected_review = work_item.projected_review
        if (
            projected_review is None
            or projected_review.classification != "findings_present"
            or projected_review.feedback is None
        ):
            return self._reject(work_item, "No actionable projected review feedback is available.")
        if request.expected_state_fingerprint != RecoveryDecisionService.state_fingerprint(
            work_item
        ):
            return self._reject(
                work_item,
                "Review-feedback request is stale because the authoritative work item changed.",
            )
        if request.occurred_at.tzinfo is None:
            return self._reject(
                work_item,
                "Review-feedback request timestamp must include a timezone.",
            )
        previous = work_item.last_revision_command or work_item.review_revision_request
        if previous is not None and (
            request.request_reference == previous.request_reference
            or previous.occurred_at.tzinfo is None
            or request.occurred_at <= previous.occurred_at
        ):
            return self._reject(
                work_item, "Review-feedback command was already consumed or is stale."
            )
        command = ReviewRevisionRequest(
            actor=request.actor,
            request_reference=request.request_reference,
            occurred_at=request.occurred_at,
            reviewed_sha=projected_review.reviewed_sha,
        )
        return ReviewFeedbackDecision(
            accepted=True,
            message="A bounded revision of the linked change request was queued.",
            work_item=work_item.model_copy(
                update={
                    "status": "review_revision_queued",
                    "review_revision_request": command,
                    "last_revision_command": command,
                }
            ),
        )

    @staticmethod
    def _reject(work_item: WorkItemState, message: str) -> ReviewFeedbackDecision:
        """Return one unchanged rejected decision."""
        return ReviewFeedbackDecision(accepted=False, message=message, work_item=work_item)
