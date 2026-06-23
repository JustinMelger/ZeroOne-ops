from zeroone_ops.models.review import PublishableReviewArtifact, PublishableReviewFinding
from zeroone_ops.services.review.pipeline.review_artifact_validator import (
    ReviewArtifactValidator,
)


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


def test_validate_rejects_findings_present_without_findings() -> None:
    result = ReviewArtifactValidator().validate(
        PublishableReviewArtifact(
            classification="findings_present",
            summary="No actionable findings in this review pass.",
            findings=[],
        )
    )

    assert result.status == "rejected"
    assert result.issues[0].rule_id == "findings_present_without_findings"


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


def test_validate_rejects_no_findings_with_findings() -> None:
    result = ReviewArtifactValidator().validate(
        PublishableReviewArtifact(
            classification="no_findings",
            summary=(
                "The updates since the last review don't introduce any new actionable concerns."
            ),
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
    assert result.issues[0].rule_id == "no_findings_with_findings"


def test_validate_rejects_manual_review_only_with_findings() -> None:
    result = ReviewArtifactValidator().validate(
        PublishableReviewArtifact(
            classification="manual_review_only",
            summary="The diff is too broad to assess reliably in this pass.",
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
    assert result.issues[0].rule_id == "manual_review_only_with_findings"


def test_validate_accepts_semantic_wording_when_shape_is_coherent() -> None:
    result = ReviewArtifactValidator().validate(
        PublishableReviewArtifact(
            classification="no_findings",
            summary="This regression breaks runtime behavior.",
            review_confidence_reason="The regression is visible in the diff.",
            findings=[],
        )
    )

    assert result.status == "valid"
    assert result.issues == []
