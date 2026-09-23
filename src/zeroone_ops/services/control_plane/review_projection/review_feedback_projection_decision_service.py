"""Apply provider-neutral review-feedback projection decisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from zeroone_ops.models.review import PublishableReviewArtifact
from zeroone_ops.models.state import utc_now
from zeroone_ops.models.work_item import (
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    WorkItemState,
)


@dataclass(frozen=True)
class ReviewFeedbackProjectionDecision:
    """Return one bounded projection update or a stable no-write reason."""

    action: str
    work_item: WorkItemState
    warning: str | None = None


class ReviewFeedbackProjectionDecisionService:
    """Decide review-feedback transitions without provider dependencies."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        """Supply the clock used when feedback requires a new operator decision."""
        self.clock = clock

    def decide(
        self,
        *,
        work_item: WorkItemState,
        artifact: PublishableReviewArtifact,
        reviewed_sha: str,
        review_note_url: str | None,
        review_note_reference: str | None,
    ) -> ReviewFeedbackProjectionDecision:
        """Project a finalized review artifact onto one linked remediation item."""
        existing = work_item.projected_review
        if (
            existing is not None
            and existing.reviewed_sha == reviewed_sha
            and existing.review_note_reference == review_note_reference
        ):
            if (
                work_item.status == "review_feedback_required"
                and work_item.review_action_required_at is None
            ):
                return ReviewFeedbackProjectionDecision(
                    "updated",
                    work_item.model_copy(update={"review_action_required_at": self.clock()}),
                )
            return ReviewFeedbackProjectionDecision("unchanged", work_item)

        feedback = build_projected_review_feedback(artifact)
        classification = artifact.classification
        warning = None
        if classification == "findings_present" and feedback is None:
            classification = "manual_review_only"
            warning = (
                "Review findings were not actionable because bounded feedback was unavailable."
            )

        cancelled_revision: dict[str, object] = {
            "claim": None,
            "review_revision_request": None,
            "last_revision_command": (
                work_item.last_revision_command or work_item.review_revision_request
            ),
        }
        # Manual review cannot authorize old feedback against a different SHA.
        # Retain the original packet and require a new operator decision.
        if (
            classification == "manual_review_only"
            and work_item.status in {"review_feedback_required", "review_revision_queued"}
            and existing is not None
            and existing.feedback is not None
        ):
            retained = work_item.model_copy(
                update={
                    **cancelled_revision,
                    "status": "review_feedback_required",
                }
            )
            if retained != work_item or work_item.review_action_required_at is None:
                retained = retained.model_copy(update={"review_action_required_at": self.clock()})
            return ReviewFeedbackProjectionDecision(
                "unchanged" if retained == work_item else "updated", retained, warning
            )

        projected_review = ProjectedReviewState(
            classification=classification,
            reviewed_sha=reviewed_sha,
            review_note_url=review_note_url,
            review_note_reference=review_note_reference,
            follow_up_required=classification == "findings_present",
            feedback=feedback,
        )
        update: dict[str, object] = {"projected_review": projected_review}
        if classification == "findings_present":
            update.update(
                {
                    "status": "review_feedback_required",
                    "review_action_required_at": self.clock(),
                    **cancelled_revision,
                }
            )
        elif work_item.status in {"review_feedback_required", "review_revision_queued"}:
            update.update({"status": "in_progress", **cancelled_revision})
        return ReviewFeedbackProjectionDecision(
            "updated",
            work_item.model_copy(update=update),
            warning,
        )


def build_projected_review_feedback(
    artifact: PublishableReviewArtifact,
) -> ProjectedReviewFeedback | None:
    """Build feedback only when the finalized artifact is actionable and bounded."""
    if artifact.classification != "findings_present" or not artifact.findings:
        return None
    try:
        findings = [
            ProjectedReviewFinding(
                title=finding.title,
                file_path=finding.file_path,
                line_start=finding.line_start,
                line_end=finding.line_end,
                evidence=finding.evidence,
                explanation=finding.explanation,
                suggested_follow_up=finding.suggested_follow_up,
            )
            for finding in artifact.findings
        ]
        return ProjectedReviewFeedback(
            summary=artifact.summary,
            finding_count=len(artifact.findings),
            findings=findings,
        )
    except ValueError:
        return None
