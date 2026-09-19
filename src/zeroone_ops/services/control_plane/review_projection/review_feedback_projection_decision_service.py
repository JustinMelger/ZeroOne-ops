"""Apply provider-neutral review-feedback projection decisions."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.review import PublishableReviewArtifact
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
            return ReviewFeedbackProjectionDecision("unchanged", work_item)

        feedback = build_projected_review_feedback(artifact)
        classification = artifact.classification
        warning = None
        if classification == "findings_present" and feedback is None:
            classification = "manual_review_only"
            warning = (
                "Review findings were not actionable because bounded feedback was unavailable."
            )

        # A manual-only review must not erase actionable feedback awaiting an operator.
        if (
            classification == "manual_review_only"
            and work_item.status == "review_feedback_required"
        ):
            return ReviewFeedbackProjectionDecision("unchanged", work_item, warning)

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
                    "claim": None,
                    "review_revision_request": None,
                }
            )
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
