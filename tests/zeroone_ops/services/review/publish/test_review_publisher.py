from typing import cast

from zeroone_ops.models.review import (
    PriorReviewInlineComment,
    PublishableReviewArtifact,
    PublishableReviewFinding,
)
from zeroone_ops.models.state import ReviewInlineCommentDecision
from zeroone_ops.services.review.publish.review_publisher import ReviewPublisher

from .support import (
    FakeGitLabReviewClient,
    build_artifact,
    build_clear_follow_up_context,
    build_context,
    build_follow_up_context,
    build_manual_review_follow_up_context,
    build_multiline_context,
    extract_machine_safe_payload,
)


def test_render_artifact_formats_findings_present() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_context(),
        artifact=build_artifact(),
    )

    assert body.startswith("**Verdict:** Concern\n**Risk:** Medium\n**Confidence:** High")
    assert "I noticed one actionable concern in these changes." in body
    assert "**Findings**" in body
    assert "1. `src/service.py`" in body
    assert "Missing test coverage." in body
    assert "The change alters branch behavior without test updates." in body
    assert "Evidence:" not in body
    assert "Follow-up:" not in body
    assert "Scope:" not in body

    payload = extract_machine_safe_payload(body)
    assert payload["schema"] == "ai-sonar-bot/review-note/v1"
    assert payload["reviewed_change_request_number"] == 17
    assert payload["reviewed_head_sha"] == "abc123"
    assert payload["classification"] == "findings_present"
    assert payload["findings_count"] == 1
    assert payload["findings"] == [
        {
            "file_path": "src/service.py",
            "issue_kind": None,
            "identity": "src/service.py::coverage-miss-test",
            "inline_comment": None,
            "legacy_identity": "src/service.py::coverage-miss-test",
            "line_end": 1,
            "line_start": 1,
            "region_hint": None,
            "severity": "medium",
            "summary": "src/service.py: Missing test coverage",
            "symbol": None,
            "title": "Missing test coverage",
        }
    ]


def test_render_artifact_uses_block_verdict_for_high_risk_findings() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_context(),
        artifact=PublishableReviewArtifact(
            classification="findings_present",
            summary="One high-risk finding.",
            review_confidence=0.88,
            findings=[
                PublishableReviewFinding(
                    severity="high",
                    file_path="src/service.py",
                    title="Unconditional exception reaches a supported runtime path",
                    evidence="The diff raises a RuntimeError unconditionally in the new branch.",
                    explanation="This can fail at runtime on supported input.",
                    suggested_follow_up="Remove the unconditional exception.",
                    issue_kind="deterministic_runtime_error",
                )
            ],
        ),
    )

    assert body.startswith("**Verdict:** Block\n**Risk:** High\n**Confidence:** High")
    assert "I'd block this because of 1 actionable concern." in body


def test_render_artifact_keeps_consequence_for_runtime_failures_when_it_adds_clarity() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_context(),
        artifact=PublishableReviewArtifact(
            classification="findings_present",
            summary="One high-risk finding.",
            review_confidence=0.88,
            findings=[
                PublishableReviewFinding(
                    severity="high",
                    file_path="src/service.py",
                    title="Unchecked access to `vehicle.types[0]` can raise `IndexError`",
                    evidence="The helper reads `vehicle.types[0]` directly.",
                    explanation="This can raise `IndexError` on valid empty-list input.",
                    suggested_follow_up="Guard the empty-list case.",
                    issue_kind="deterministic_runtime_error",
                )
            ],
        ),
    )

    assert (
        "Unchecked access to `vehicle.types[0]` can raise `IndexError`.\n"
        "   This can raise `IndexError` on valid empty-list input."
    ) in body


def test_render_artifact_uses_two_sentences_when_behavioral_consequence_is_not_obvious() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_context(),
        artifact=PublishableReviewArtifact(
            classification="findings_present",
            summary="One medium-risk finding.",
            review_confidence=0.74,
            findings=[
                PublishableReviewFinding(
                    severity="medium",
                    file_path="src/config.py",
                    title="Missing lookup-country config now defaults silently to `{}`",
                    evidence="The new code path uses an empty-dict fallback.",
                    explanation=(
                        "This turns a configuration error into silent misconfiguration, "
                        "which is harder to detect in production."
                    ),
                    suggested_follow_up="Fail fast when the configuration is missing.",
                    issue_kind="behavioral_regression",
                )
            ],
        ),
    )

    assert "Missing lookup-country config now defaults silently to `{}`." in body
    assert (
        "This turns a configuration error into silent misconfiguration, "
        "which is harder to detect in production."
    ) in body


def test_render_artifact_renders_advisory_notes_in_separate_section() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_context(),
        artifact=build_artifact(
            advisory_notes=[
                (
                    "Repository guidance prefers clearer naming here; "
                    "this example remains harder to scan."
                )
            ]
        ),
    )

    assert "Style Observations (Repository Guidance):" in body
    assert (
        "- Repository guidance prefers clearer naming here; this example remains harder to scan."
        in body
    )
    assert "1. `src/service.py`" in body


def test_render_artifact_formats_no_findings() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_context(),
        artifact=build_artifact(classification="no_findings"),
    )

    assert "I don't see any actionable concerns in these changes." in body
    assert body.startswith("**Verdict:** Clear\n**Confidence:** High")
    assert "Risk:" not in body
    assert "Continuity:" not in body
    assert "Scope:" not in body
    assert "Notes:" not in body

    payload = extract_machine_safe_payload(body)
    assert payload["classification"] == "no_findings"
    assert payload["findings_count"] == 0
    assert payload["findings"] == []


def test_render_artifact_acknowledges_previous_pass_for_no_findings_follow_up() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_follow_up_context(),
        artifact=build_artifact(
            classification="no_findings",
            summary="The earlier concern is no longer present in the updated changes.",
            follow_up_lines=["Follow-up review after the earlier bot pass on `abc123`."],
        ),
    )

    assert (
        "I took another look, and I don't see any actionable concerns in these changes now."
    ) in body
    assert "The earlier concern is no longer present in the updated changes." in body


def test_render_artifact_does_not_repeat_clear_detail_after_prior_clear() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_clear_follow_up_context(),
        artifact=build_artifact(
            classification="no_findings",
            summary="The earlier concern is no longer present in the updated changes.",
            follow_up_lines=["Follow-up review after the earlier bot pass on `abc123`."],
        ),
    )

    assert (
        "I took another look, and I don't see any actionable concerns in these changes now."
    ) in body
    visible_body = body.split("<!-- ai-sonar-bot:review-note:v1", 1)[0]
    assert "The earlier concern is no longer present in the updated changes." not in visible_body


def test_publish_artifact_sends_rendered_note_body() -> None:
    review_client = FakeGitLabReviewClient()
    publisher = ReviewPublisher(review_client)

    result = publisher.publish_artifact(
        repository_id="123",
        change_request_number=17,
        context=build_context(),
        artifact=build_artifact(),
    )

    assert result.note is not None
    assert result.note.id == 55
    assert review_client.published_body is not None
    assert "Missing test coverage" in review_client.published_body
    assert result.artifact is not None
    assert result.artifact.findings[0].inline_comment is None


def test_publish_artifact_creates_inline_comment_after_summary_note_when_requested() -> None:
    review_client = FakeGitLabReviewClient()
    publisher = ReviewPublisher(review_client)
    artifact = build_artifact()

    result = publisher.publish_artifact(
        repository_id="123",
        change_request_number=17,
        context=build_context(),
        artifact=artifact,
        inline_comment_decisions=[
            ReviewInlineCommentDecision(
                finding_identity=artifact.findings[0].stable_identity,
                severity=artifact.findings[0].severity,
                file_path=artifact.findings[0].file_path,
                line_start=artifact.findings[0].line_start,
                line_end=artifact.findings[0].line_end,
                region_hint=artifact.findings[0].region_hint,
                inline_comments_enabled=True,
                location_trust="trusted",
                existing_inline_comment_found=False,
                anchor_reuse_decision="new",
                anchor_reuse_reason="trusted_new_anchor",
            )
        ],
    )

    assert review_client.inline_comments
    assert review_client.inline_comments[0][1] == 1
    assert review_client.inline_comments[0][0] == "Missing test coverage."
    assert result.artifact is not None
    assert result.artifact.findings[0].inline_comment is not None
    assert result.artifact.findings[0].inline_comment.comment_id == "789"
    assert result.inline_comment_decisions is not None
    assert result.warning_message is None


def test_publish_artifact_keeps_inline_comments_to_one_issue_sentence() -> None:
    review_client = FakeGitLabReviewClient()
    publisher = ReviewPublisher(review_client)
    artifact = PublishableReviewArtifact(
        classification="findings_present",
        summary="One high-risk finding.",
        findings=[
            PublishableReviewFinding(
                severity="high",
                file_path="src/service.py",
                line_start=1,
                line_end=1,
                stable_identity="src/service.py::unchecked-types-index",
                legacy_identity="src/service.py::unchecked-types-index",
                title="Unchecked access to `vehicle.types[0]` can raise `IndexError`",
                evidence="The helper reads `vehicle.types[0]` directly.",
                explanation="This can raise `IndexError` on valid empty-list input.",
                suggested_follow_up="Guard the empty-list case.",
                issue_kind="deterministic_runtime_error",
            )
        ],
    )

    publisher.publish_artifact(
        repository_id="123",
        change_request_number=17,
        context=build_context(),
        artifact=artifact,
        inline_comment_decisions=[
            ReviewInlineCommentDecision(
                finding_identity=artifact.findings[0].stable_identity,
                severity=artifact.findings[0].severity,
                file_path=artifact.findings[0].file_path,
                line_start=artifact.findings[0].line_start,
                line_end=artifact.findings[0].line_end,
                region_hint=artifact.findings[0].region_hint,
                inline_comments_enabled=True,
                location_trust="trusted",
                existing_inline_comment_found=False,
                anchor_reuse_decision="new",
                anchor_reuse_reason="trusted_new_anchor",
            )
        ],
    )

    assert review_client.inline_comments
    assert (
        review_client.inline_comments[0][0]
        == "Unchecked access to `vehicle.types[0]` can raise `IndexError`."
    )


def test_publish_artifact_surfaces_inline_comment_publish_warning() -> None:
    review_client = FakeGitLabReviewClient()
    review_client.fail_inline_publish = True
    publisher = ReviewPublisher(review_client)
    artifact = build_artifact()

    result = publisher.publish_artifact(
        repository_id="123",
        change_request_number=17,
        context=build_context(),
        artifact=artifact,
        inline_comment_decisions=[
            ReviewInlineCommentDecision(
                finding_identity=artifact.findings[0].stable_identity,
                severity=artifact.findings[0].severity,
                file_path=artifact.findings[0].file_path,
                line_start=artifact.findings[0].line_start,
                line_end=artifact.findings[0].line_end,
                region_hint=artifact.findings[0].region_hint,
                inline_comments_enabled=True,
                location_trust="trusted",
                existing_inline_comment_found=False,
                anchor_reuse_decision="new",
                anchor_reuse_reason="trusted_new_anchor",
            )
        ],
    )

    assert result.note is not None
    assert result.warning_message is not None
    assert "could not be published" in result.warning_message
    assert result.artifact.findings[0].inline_comment is None


def test_publish_artifact_surfaces_authoritative_note_update_warning() -> None:
    review_client = FakeGitLabReviewClient()
    review_client.fail_note_update = True
    publisher = ReviewPublisher(review_client)
    artifact = build_artifact()

    result = publisher.publish_artifact(
        repository_id="123",
        change_request_number=17,
        context=build_context(),
        artifact=artifact,
        inline_comment_decisions=[
            ReviewInlineCommentDecision(
                finding_identity=artifact.findings[0].stable_identity,
                severity=artifact.findings[0].severity,
                file_path=artifact.findings[0].file_path,
                line_start=artifact.findings[0].line_start,
                line_end=artifact.findings[0].line_end,
                region_hint=artifact.findings[0].region_hint,
                inline_comments_enabled=True,
                location_trust="trusted",
                existing_inline_comment_found=False,
                anchor_reuse_decision="new",
                anchor_reuse_reason="trusted_new_anchor",
            )
        ],
    )

    assert result.note is not None
    assert result.warning_message is not None
    assert "updating the authoritative review note failed" in result.warning_message
    assert "local mirrored continuity was preserved" in result.warning_message
    assert result.artifact.findings[0].inline_comment is not None
    assert result.artifact.findings[0].inline_comment.comment_id == "789"


def test_publish_artifact_prefers_latest_changed_line_within_finding_range() -> None:
    review_client = FakeGitLabReviewClient()
    publisher = ReviewPublisher(review_client)
    artifact = PublishableReviewArtifact(
        classification="findings_present",
        summary="One medium-risk finding.",
        findings=[
            PublishableReviewFinding(
                severity="medium",
                file_path="src/service.py",
                line_start=73,
                line_end=75,
                stable_identity="src/service.py::vehicle-id-normalization",
                legacy_identity="src/service.py::vehicle-id-normalization",
                title="VLAPI vehicle_id is not normalized before article lookup",
                evidence="The normalized value is only made concrete at the later lookup step.",
                explanation=(
                    "The wrong value shape reaches article lookup when normalization "
                    "is inconsistent."
                ),
                suggested_follow_up="Normalize the derived vehicle id before lookup.",
            )
        ],
    )

    publisher.publish_artifact(
        repository_id="123",
        change_request_number=17,
        context=build_multiline_context(),
        artifact=artifact,
        inline_comment_decisions=[
            ReviewInlineCommentDecision(
                finding_identity=artifact.findings[0].stable_identity,
                severity=artifact.findings[0].severity,
                file_path=artifact.findings[0].file_path,
                line_start=artifact.findings[0].line_start,
                line_end=artifact.findings[0].line_end,
                region_hint=artifact.findings[0].region_hint,
                inline_comments_enabled=True,
                location_trust="trusted",
                existing_inline_comment_found=False,
                anchor_reuse_decision="new",
                anchor_reuse_reason="trusted_new_anchor",
            )
        ],
    )

    assert review_client.inline_comments
    assert review_client.inline_comments[0][1] == 75


def test_render_artifact_embeds_inline_comment_metadata_when_present() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_context(),
        artifact=PublishableReviewArtifact(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=[
                PublishableReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    line_start=4,
                    line_end=4,
                    stable_identity="src/service.py::coverage-miss-test",
                    legacy_identity="src/service.py::coverage-miss-test",
                    title="Missing test coverage",
                    evidence="The diff changes `value = 1` to `value = 2` without tests.",
                    explanation="The change alters branch behavior without regression coverage.",
                    suggested_follow_up="Add a regression test.",
                    inline_comment=PriorReviewInlineComment(
                        comment_id="789",
                        comment_url="https://gitlab.example.com/comment/789",
                        status="published",
                        anchor_file_path="src/service.py",
                        anchor_line_start=4,
                        anchor_line_end=4,
                    ),
                )
            ],
        ),
    )

    payload = extract_machine_safe_payload(body)
    findings = cast(list[dict[str, object]], payload["findings"])
    assert findings[0]["inline_comment"] == {
        "anchor_file_path": "src/service.py",
        "anchor_line_end": 4,
        "anchor_line_start": 4,
        "comment_id": "789",
        "comment_url": "https://gitlab.example.com/comment/789",
        "status": "published",
    }


def test_render_artifact_includes_follow_up_lines_when_available() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_follow_up_context(),
        artifact=build_artifact(
            follow_up_lines=[
                "Follow-up review after the earlier bot pass on `abc123`.",
                "An earlier concern from the last pass still appears unresolved.",
                "",
            ]
        ),
    )

    assert "**Continuity:** 1 repeated" in body
    assert "Follow-up review after the earlier bot pass on `abc123`." not in body
    assert (
        "I took another look, and I still notice one actionable concern in these changes." in body
    )


def test_render_artifact_uses_neutral_follow_up_wording_for_ambiguous_overlap() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_follow_up_context(),
        artifact=build_artifact(
            follow_up_lines=[
                "Follow-up review after the earlier bot pass on `abc123`.",
                (
                    "This pass may overlap with an earlier concern, but the overlap is "
                    "not fully clear from the current changes."
                ),
                "",
            ]
        ),
    )

    assert "**Continuity:** overlap unclear" in body


def test_render_artifact_acknowledges_new_follow_up_concern() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_clear_follow_up_context(),
        artifact=build_artifact(
            follow_up_lines=[
                "Follow-up review after the earlier bot pass on `abc123`.",
                "This pass introduces a new concern in the updated changes.",
                "",
            ]
        ),
    )

    assert "**Continuity:** 1 new" in body
    assert "I took another look, and I noticed one actionable concern in these changes now." in body


def test_render_artifact_omits_follow_up_wording_when_missing() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_follow_up_context(),
        artifact=build_artifact(),
    )

    assert "Continuity:" not in body


def test_render_artifact_keeps_manual_review_only_overlap_wording_conservative() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_follow_up_context(),
        artifact=build_artifact(
            classification="manual_review_only",
            summary="The diff is too broad to assess reliably in this pass.",
            follow_up_lines=[
                "Follow-up review after the earlier bot pass on `abc123`.",
                (
                    "This pass may still relate to an earlier concern, but the current "
                    "review was not confident enough to verify continuity fully."
                ),
                "",
            ],
        ),
    )

    assert body.startswith("**Verdict:** Needs review\n**Confidence:** High")
    assert "Risk:" not in body
    assert "Continuity:" not in body
    assert (
        "I took another look, but I couldn't review these changes confidently enough "
        "to confirm the earlier concern this time." in body
    )
    assert "The diff is too broad to assess reliably in this pass." in body
    assert "A human review is still needed before treating these changes as safe." in body


def test_render_artifact_acknowledges_manual_review_after_clear() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_clear_follow_up_context(),
        artifact=build_artifact(
            classification="manual_review_only",
            summary="The diff is too broad to assess reliably in this pass.",
            follow_up_lines=[
                "Follow-up review after the earlier bot pass on `abc123`.",
                (
                    "This pass broadened enough that the current review was not "
                    "confident enough to assess it reliably."
                ),
                "",
            ],
        ),
    )

    assert (
        "I took another look, but I couldn't review these changes confidently "
        "enough to call them clear this time." in body
    )


def test_render_artifact_acknowledges_concern_after_manual_review() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_manual_review_follow_up_context(),
        artifact=build_artifact(
            follow_up_lines=[
                "Follow-up review after the earlier bot pass on `abc123`.",
                "This pass introduces a new concern in the updated changes.",
                "",
            ]
        ),
    )

    assert "I took another look, and I now notice one actionable concern in these changes." in body
