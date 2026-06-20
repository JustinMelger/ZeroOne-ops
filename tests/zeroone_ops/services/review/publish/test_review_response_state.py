from zeroone_ops.models.review import PublishableReviewArtifact
from zeroone_ops.services.review.publish.review_response_state import (
    render_confidence_label,
    render_continuity_line,
    render_risk,
    render_summary_sentence,
    render_verdict,
)

from .support import (
    build_artifact,
    build_clear_follow_up_context,
    build_context,
    build_follow_up_context,
    build_manual_review_follow_up_context,
)


def test_render_verdict_for_no_findings() -> None:
    assert render_verdict(build_artifact(classification="no_findings")) == "Clear"


def test_render_verdict_for_manual_review_only() -> None:
    assert render_verdict(build_artifact(classification="manual_review_only")) == "Needs review"


def test_render_verdict_for_high_risk_findings() -> None:
    artifact = PublishableReviewArtifact(
        classification="findings_present",
        summary="One high-risk finding.",
        findings=[build_artifact().findings[0].model_copy(update={"severity": "high"})],
    )
    assert render_verdict(artifact) == "Block"


def test_render_risk_for_medium_findings() -> None:
    assert render_risk(build_artifact()) == "Medium"


def test_render_confidence_label_defaults_to_medium_when_missing() -> None:
    assert (
        render_confidence_label(build_artifact().model_copy(update={"review_confidence": None}))
        == "Medium"
    )


def test_render_continuity_line_for_repeated_concern() -> None:
    artifact = build_artifact(
        follow_up_lines=[
            "Follow-up review after the earlier bot pass on `abc123`.",
            "An earlier concern from the last pass still appears unresolved.",
            "",
        ]
    )
    assert render_continuity_line(artifact) == "**Continuity:** 1 repeated"


def test_render_summary_sentence_for_first_pass_clear() -> None:
    assert (
        render_summary_sentence(
            context=build_context(),
            artifact=build_artifact(classification="no_findings"),
        )
        == "I don't see any actionable concerns in these changes."
    )


def test_render_summary_sentence_for_clear_after_clear() -> None:
    assert (
        render_summary_sentence(
            context=build_clear_follow_up_context(),
            artifact=build_artifact(classification="no_findings"),
        )
        == "I took another look, and I don't see any actionable concerns in these changes now."
    )


def test_render_summary_sentence_for_concern_after_clear() -> None:
    assert (
        render_summary_sentence(
            context=build_clear_follow_up_context(),
            artifact=build_artifact(),
        )
        == "I took another look, and I noticed one actionable concern in these changes now."
    )


def test_render_summary_sentence_for_concern_after_concern() -> None:
    assert (
        render_summary_sentence(
            context=build_follow_up_context(),
            artifact=build_artifact(),
        )
        == "I took another look, and I still notice one actionable concern in these changes."
    )


def test_render_summary_sentence_for_concern_after_manual_review() -> None:
    assert (
        render_summary_sentence(
            context=build_manual_review_follow_up_context(),
            artifact=build_artifact(),
        )
        == "I took another look, and I now notice one actionable concern in these changes."
    )


def test_render_summary_sentence_for_manual_review_after_clear() -> None:
    assert (
        render_summary_sentence(
            context=build_clear_follow_up_context(),
            artifact=build_artifact(classification="manual_review_only"),
        )
        == "I took another look, but I couldn't review these changes confidently "
        "enough to call them clear this time."
    )


def test_render_summary_sentence_for_manual_review_after_concern() -> None:
    assert (
        render_summary_sentence(
            context=build_follow_up_context(),
            artifact=build_artifact(classification="manual_review_only"),
        )
        == "I took another look, but I couldn't review these changes confidently "
        "enough to confirm the earlier concern this time."
    )
