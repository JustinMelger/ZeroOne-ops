from datetime import UTC, datetime

from zeroone_ops.models.review import (
    OverlapReconciliationResult,
    OverlapResolution,
    PrecisionAcceptedFinding,
    PrecisionReviewDecision,
    ReconciledReviewDecision,
)
from zeroone_ops.services.review.pipeline.review_artifact_builder import (
    ReviewArtifactBuilder,
)
from zeroone_ops.services.review.pipeline.review_reconciled_decision_builder import (
    build_reconciled_review_decision,
)


def build_decision(classification: str = "findings_present") -> ReconciledReviewDecision:
    return build_reconciled_review_decision(
        PrecisionReviewDecision(
            review_classification=classification,
            decision_summary=(
                "One medium-risk finding."
                if classification == "findings_present"
                else "No findings."
            ),
            decision_rationale="The finding is grounded in the reviewed diff.",
            confidence_level=0.84,
            advisory_notes=[
                (
                    "Repository guidance prefers clearer naming here; "
                    "the example remains harder to scan."
                )
            ],
            accepted_findings=(
                []
                if classification != "findings_present"
                else [
                    PrecisionAcceptedFinding(
                        source_candidate_ids=["candidate-1"],
                        severity="medium",
                        file_path="src/service.py",
                        title="Missing regression coverage",
                        summary="Missing regression coverage",
                        evidence=[
                            "The diff changes `value = 1` to `value = 2` without test updates."
                        ],
                        why_it_matters=("The branch behavior changes without regression coverage."),
                        recommended_follow_up="Add a regression test.",
                    )
                ]
            ),
            dropped_candidates=[],
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
    assert artifact.advisory_notes == [
        "Repository guidance prefers clearer naming here; the example remains harder to scan."
    ]
    assert len(artifact.findings) == 1
    assert artifact.findings[0].title == "Missing regression coverage"
    assert artifact.follow_up_lines == []


def test_build_sets_no_findings_summary_from_publish_shape() -> None:
    artifact = (
        ReviewArtifactBuilder().build(reconciled_decision=build_decision("no_findings")).artifact
    )

    assert artifact.classification == "no_findings"
    assert artifact.summary == "No actionable findings in this review pass."


def test_build_rewrites_internal_no_findings_rationale_for_publish() -> None:
    decision = build_decision("no_findings").model_copy(
        update={
            "decision_rationale": (
                "The precision stage is bounded to the provided grounded candidate "
                "set, which is empty."
            )
        }
    )

    artifact = ReviewArtifactBuilder().build(reconciled_decision=decision).artifact

    assert artifact.review_confidence_reason is not None
    assert "precision stage" not in artifact.review_confidence_reason.lower()
    assert "grounded candidate set" not in artifact.review_confidence_reason.lower()
    assert "supported-path regression" in artifact.review_confidence_reason


def test_build_rewrites_internal_follow_up_no_findings_rationale_for_publish() -> None:
    decision = build_decision("no_findings").model_copy(
        update={
            "decision_rationale": (
                "There is not enough candidate-backed evidence to justify an actionable finding."
            )
        }
    )

    artifact = (
        ReviewArtifactBuilder()
        .build(
            reconciled_decision=decision,
            overlap_result=OverlapReconciliationResult(
                prior_reviewed_head_sha="abc123",
                resolutions=[],
            ),
        )
        .artifact
    )

    assert artifact.review_confidence_reason is not None
    assert "candidate-backed evidence" not in artifact.review_confidence_reason.lower()
    assert "earlier concern" in artifact.review_confidence_reason.lower()
    assert (
        artifact.summary
        == "The updates since the last review don't introduce any new actionable concerns."
    )


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

    assert "advisory_notes" not in review_result.model_dump()
    assert review_result.follow_up_lines == artifact.follow_up_lines
