from zeroone_ops.models.review import PublishableReviewArtifact, PublishableReviewFinding
from zeroone_ops.services.review.review_artifact_validator import ReviewArtifactValidator


def test_validate_accepts_consistent_findings_present_artifact() -> None:
    result = ReviewArtifactValidator().validate(
        PublishableReviewArtifact(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=[
                PublishableReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing test coverage",
                    evidence="The diff changes `value = 1` to `value = 2` without tests.",
                    explanation="The change alters behavior without test updates.",
                    suggested_follow_up="Add a regression test.",
                )
            ],
        )
    )

    assert result.status == "valid"
    assert result.issues == []


def test_validate_rejects_findings_present_summary_that_denies_findings() -> None:
    result = ReviewArtifactValidator().validate(
        PublishableReviewArtifact(
            classification="findings_present",
            summary="No actionable findings in this review pass.",
            findings=[
                PublishableReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing test coverage",
                    evidence="The diff changes `value = 1` to `value = 2` without tests.",
                    explanation="The change alters behavior without test updates.",
                    suggested_follow_up="Add a regression test.",
                )
            ],
        )
    )

    assert result.status == "rejected"
    assert result.issues[0].rule_id == "findings_present_summary_denies_findings"


def test_build_manual_review_only_fallback_preserves_follow_up_lines() -> None:
    validator = ReviewArtifactValidator()
    artifact = PublishableReviewArtifact(
        classification="no_findings",
        summary="This regression breaks runtime behavior.",
        review_confidence_reason="The regression is visible in the diff.",
        follow_up_lines=["Follow-up review after the earlier bot pass on `abc123`."],
    )
    validation_result = validator.validate(artifact)

    fallback = validator.build_manual_review_only_fallback(
        artifact=artifact,
        validation_result=validation_result,
    )

    assert fallback.classification == "manual_review_only"
    assert fallback.follow_up_lines == artifact.follow_up_lines
    assert "internally inconsistent artifact" in fallback.summary


def test_validate_accepts_benign_no_findings_reasoning() -> None:
    result = ReviewArtifactValidator().validate(
        PublishableReviewArtifact(
            classification="no_findings",
            summary="No actionable findings in this review pass.",
            review_confidence_reason=(
                "The reviewed change is deterministic and behavior-preserving."
            ),
            findings=[],
        )
    )

    assert result.status == "valid"
    assert result.issues == []
