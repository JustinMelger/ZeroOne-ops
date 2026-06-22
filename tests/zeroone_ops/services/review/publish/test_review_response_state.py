from zeroone_ops.models.review import (
    ChangeRequestReviewContext,
    PriorReviewContext,
    PriorReviewPass,
    PublishableReviewArtifact,
)
from zeroone_ops.services.review.publish.review_response_state import (
    render_confidence_label,
    render_continuity_line,
    render_risk,
    render_summary_sentence,
    render_verdict,
    should_render_no_findings_detail,
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
    assert render_continuity_line(artifact) == "**Since last review:** 1 repeated finding"


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


def test_render_summary_sentence_uses_newest_prior_pass_when_multiple_are_present() -> None:
    context = ChangeRequestReviewContext.model_validate(
        build_context().model_dump()
        | {
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="newest",
                        classification="no_findings",
                        findings_count=0,
                        summary="No actionable findings in the earlier pass.",
                        findings=[],
                    ),
                    PriorReviewPass(
                        reviewed_head_sha="older",
                        classification="findings_present",
                        findings_count=1,
                        summary="One earlier concern still needs attention.",
                        findings=[],
                    ),
                ],
            )
        }
    )

    assert (
        render_summary_sentence(
            context=context,
            artifact=build_artifact(),
        )
        == "I took another look, and one actionable concern stands out in these changes now."
    )


def test_should_render_no_findings_detail_after_concern() -> None:
    assert should_render_no_findings_detail(
        context=build_follow_up_context(),
        artifact=build_artifact(classification="no_findings"),
    )


def test_should_render_no_findings_detail_after_clear() -> None:
    assert should_render_no_findings_detail(
        context=build_clear_follow_up_context(),
        artifact=build_artifact(classification="no_findings"),
    )


def test_should_render_no_findings_detail_after_manual_review() -> None:
    assert should_render_no_findings_detail(
        context=build_manual_review_follow_up_context(),
        artifact=build_artifact(classification="no_findings"),
    )


def test_should_render_no_findings_detail_on_first_pass_clear() -> None:
    assert should_render_no_findings_detail(
        context=build_context(),
        artifact=build_artifact(classification="no_findings"),
    )


def test_render_summary_sentence_for_concern_after_clear() -> None:
    assert (
        render_summary_sentence(
            context=build_clear_follow_up_context(),
            artifact=build_artifact(),
        )
        == "I took another look, and one actionable concern stands out in these changes now."
    )


def test_render_summary_sentence_for_concern_after_concern() -> None:
    assert (
        render_summary_sentence(
            context=build_follow_up_context(),
            artifact=build_artifact(),
        )
        == "I took another look, and one actionable concern still stands out in these changes."
    )


def test_render_summary_sentence_for_concern_after_manual_review() -> None:
    assert (
        render_summary_sentence(
            context=build_manual_review_follow_up_context(),
            artifact=build_artifact(),
        )
        == "I took another look, and one actionable concern stands out in these changes now."
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
