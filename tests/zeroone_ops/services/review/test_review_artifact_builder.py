from datetime import UTC, datetime

from zeroone_ops.models.review import (
    OverlapReconciliationResult,
    OverlapResolution,
    ReconciledReviewDecision,
    ReviewFinding,
    ReviewResult,
)
from zeroone_ops.services.review.review_artifact_builder import ReviewArtifactBuilder


def build_decision(classification: str = "findings_present") -> ReconciledReviewDecision:
    findings = (
        []
        if classification != "findings_present"
        else [
            ReviewFinding(
                severity="medium",
                file_path="src/service.py",
                title="Missing regression coverage",
                evidence="The diff changes `value = 1` to `value = 2` without test updates.",
                explanation="The branch behavior changes without regression coverage.",
                suggested_follow_up="Add a regression test.",
            )
        ]
    )
    return ReconciledReviewDecision.from_review_result(
        ReviewResult(
            classification=classification,
            summary=(
                "One medium-risk finding."
                if classification == "findings_present"
                else "No findings."
            ),
            review_confidence=0.84,
            review_confidence_reason="The finding is grounded in the reviewed diff.",
            findings=findings,
        ),
        prior_review_context_used=False,
        same_sha_review=False,
        repair_allowed=classification != "manual_review_only",
        reconciled_at=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        pipeline_version="review-staged-v1",
    )


def test_build_preserves_finding_content_for_findings_present() -> None:
    artifact = ReviewArtifactBuilder().build(reconciled_decision=build_decision()).artifact

    assert artifact.classification == "findings_present"
    assert artifact.summary == "One medium-risk finding."
    assert artifact.review_confidence == 0.84
    assert artifact.review_confidence_reason == "The finding is grounded in the reviewed diff."
    assert len(artifact.findings) == 1
    assert artifact.findings[0].title == "Missing regression coverage"
    assert artifact.follow_up_lines == []


def test_build_sets_no_findings_summary_from_publish_shape() -> None:
    artifact = (
        ReviewArtifactBuilder().build(reconciled_decision=build_decision("no_findings")).artifact
    )

    assert artifact.classification == "no_findings"
    assert artifact.summary == "No actionable findings in this review pass."


def test_build_attaches_follow_up_lines_from_overlap_result() -> None:
    artifact = (
        ReviewArtifactBuilder()
        .build(
            reconciled_decision=build_decision(),
            overlap_result=OverlapReconciliationResult(
                prior_reviewed_head_sha="abc123",
                resolutions=[
                    OverlapResolution(
                        outcome="still_unresolved",
                        current_finding_index=0,
                        prior_finding_index=0,
                        related_prior_finding_indices=[0],
                    )
                ],
            ),
        )
        .artifact
    )

    assert artifact.follow_up_lines == [
        "Follow-up review after the earlier bot pass on `abc123`.",
        "An earlier concern from the last pass still appears unresolved.",
        "",
    ]


def test_artifact_to_review_result_preserves_follow_up_lines() -> None:
    artifact = (
        ReviewArtifactBuilder()
        .build(
            reconciled_decision=build_decision(),
            overlap_result=OverlapReconciliationResult(
                prior_reviewed_head_sha="abc123",
                resolutions=[
                    OverlapResolution(
                        outcome="still_unresolved",
                        current_finding_index=0,
                        prior_finding_index=0,
                        related_prior_finding_indices=[0],
                    )
                ],
            ),
        )
        .artifact
    )

    review_result = artifact.to_review_result()

    assert review_result.follow_up_lines == artifact.follow_up_lines
