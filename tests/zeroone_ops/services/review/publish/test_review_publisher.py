import json
from typing import cast

from zeroone_ops.models.gitlab import GitLabMergeRequestState, MergeRequestNote
from zeroone_ops.models.review import (
    ChangeRequestDiffRefs,
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewInlineComment,
    PriorReviewPass,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    ReviewClassification,
    ReviewFileContext,
)
from zeroone_ops.models.state import ReviewInlineCommentDecision
from zeroone_ops.providers.review.platform import ReviewPlatformClientError
from zeroone_ops.services.review.publish.review_publisher import ReviewPublisher


def extract_machine_safe_payload(body: str) -> dict[str, object]:
    start_marker = "<!-- ai-sonar-bot:review-note:v1\n"
    end_marker = "\n-->"
    start = body.index(start_marker) + len(start_marker)
    end = body.index(end_marker, start)
    return cast(dict[str, object], json.loads(body[start:end]))


def build_context() -> ChangeRequestReviewContext:
    return ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        diff_refs=ChangeRequestDiffRefs(
            base_sha="base123",
            start_sha="start123",
            head_sha="abc123",
        ),
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )


def build_multiline_context() -> ChangeRequestReviewContext:
    return ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        diff_refs=ChangeRequestDiffRefs(
            base_sha="base123",
            start_sha="start123",
            head_sha="abc123",
        ),
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -73,3 +73,3 @@",
                start_line=73,
                end_line=75,
                content=(
                    "  73: raw_vehicle_id = vehicle.get('vehicle_id')\n"
                    "  74: normalized_vehicle_id = raw_vehicle_id.strip()\n"
                    "  75: return lookup_articles(normalized_vehicle_id)\n"
                ),
                full_file_included=True,
                truncated=False,
            )
        ],
    )


def build_follow_up_context() -> ChangeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="findings_present",
                        findings_count=1,
                        summary="One earlier concern still needs attention.",
                        findings=[
                            PriorReviewFinding(
                                identity="src/service.py::coverage-miss-test",
                                summary="src/service.py: Missing test coverage",
                                severity="medium",
                            )
                        ],
                    )
                ],
            ),
        }
    )


def build_ambiguous_follow_up_context() -> ChangeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="findings_present",
                        findings_count=1,
                        summary="One earlier concern still needs attention.",
                        findings=[
                            PriorReviewFinding(
                                summary="Earlier concern around helper behavior",
                                severity="medium",
                            )
                        ],
                    )
                ],
            ),
        }
    )


def build_mixed_ambiguity_follow_up_context() -> ChangeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="findings_present",
                        findings_count=2,
                        summary="Two earlier concerns still need attention.",
                        findings=[
                            PriorReviewFinding(
                                identity="src/service.py::coverage-miss-test",
                                summary="src/service.py: Missing test coverage",
                                severity="medium",
                            ),
                            PriorReviewFinding(
                                summary="Earlier concern around helper behavior",
                                severity="medium",
                            ),
                        ],
                    )
                ],
            ),
        }
    )


def build_variant_title_follow_up_context() -> ChangeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "ghi789",
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="def456",
                        classification="findings_present",
                        findings_count=2,
                        summary="Two earlier concerns still need attention.",
                        findings=[
                            PriorReviewFinding(
                                identity=(
                                    "bnl_app/functions/vehicle_articles_functions.py::"
                                    "cylinder-except-fail-helper-lookup-unconditional"
                                ),
                                summary=(
                                    "bnl_app/functions/vehicle_articles_functions.py: "
                                    "Unconditional exception breaks cylinder lookup helper"
                                ),
                                severity="high",
                            ),
                            PriorReviewFinding(
                                identity=(
                                    "bnl_app/functions/vehicle_functions.py::"
                                    "detail-except-fail-lookup-unconditional-vehicle"
                                ),
                                summary=(
                                    "bnl_app/functions/vehicle_functions.py: "
                                    "Unconditional exception breaks vehicle detail retrieval"
                                ),
                                severity="high",
                            ),
                        ],
                    )
                ],
            ),
        }
    )


class FakeGitLabReviewClient:
    def __init__(self) -> None:
        self.published_body: str | None = None
        self.inline_comments: list[tuple[str, int]] = []
        self.updated_body: str | None = None
        self.fail_inline_publish = False
        self.fail_note_update = False

    def create_merge_request_note(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        body: str,
    ) -> MergeRequestNote:
        del project_id, merge_request_iid
        self.published_body = body
        return MergeRequestNote(
            id=55,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
        )

    def create_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
    ) -> MergeRequestNote:
        return self.create_merge_request_note(
            project_id=repository_id,
            merge_request_iid=change_request_number,
            body=body,
        )

    def list_open_merge_requests(self, *, project_id: str) -> list[ChangeRequestReviewCandidate]:
        del project_id
        raise NotImplementedError

    def get_merge_request(
        self, *, project_id: str, merge_request_iid: int
    ) -> ChangeRequestReviewCandidate:
        del project_id, merge_request_iid
        raise NotImplementedError

    def get_merge_request_state(
        self, *, project_id: str, merge_request_iid: int
    ) -> GitLabMergeRequestState:
        del project_id, merge_request_iid
        raise NotImplementedError

    def list_merge_request_notes(
        self, *, project_id: str, merge_request_iid: int
    ) -> list[MergeRequestNote]:
        del project_id, merge_request_iid
        raise NotImplementedError

    def get_current_user_username(self) -> str:
        return "zeroone-ops"

    def update_merge_request_note(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        note_id: int,
        body: str,
    ) -> MergeRequestNote:
        del project_id, merge_request_iid, note_id
        if self.fail_note_update:
            raise ReviewPlatformClientError("update failed")
        self.updated_body = body
        return MergeRequestNote(
            id=55,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
        )

    def update_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        note_id: int,
        body: str,
    ) -> MergeRequestNote:
        return self.update_merge_request_note(
            project_id=repository_id,
            merge_request_iid=change_request_number,
            note_id=note_id,
            body=body,
        )

    def create_merge_request_inline_comment(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        body: str,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        old_path: str,
        new_path: str,
        new_line: int,
    ) -> MergeRequestNote:
        del project_id, merge_request_iid, base_sha, start_sha, head_sha, old_path, new_path
        if self.fail_inline_publish:
            raise ReviewPlatformClientError("inline failed")
        self.inline_comments.append((body, new_line))
        return MergeRequestNote(
            id=789,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_789",
        )

    def create_change_request_inline_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        old_path: str,
        new_path: str,
        new_line: int,
    ) -> MergeRequestNote:
        return self.create_merge_request_inline_comment(
            project_id=repository_id,
            merge_request_iid=change_request_number,
            body=body,
            base_sha=base_sha,
            start_sha=start_sha,
            head_sha=head_sha,
            old_path=old_path,
            new_path=new_path,
            new_line=new_line,
        )


def build_artifact(
    *,
    classification: ReviewClassification = "findings_present",
    summary: str | None = None,
    follow_up_lines: list[str] | None = None,
    advisory_notes: list[str] | None = None,
) -> PublishableReviewArtifact:
    findings = (
        []
        if classification != "findings_present"
        else [
            PublishableReviewFinding(
                severity="medium",
                file_path="src/service.py",
                line_start=1,
                line_end=1,
                stable_identity="src/service.py::coverage-miss-test",
                legacy_identity="src/service.py::coverage-miss-test",
                title="Missing test coverage",
                evidence="The diff changes `value = 1` to `value = 2` without any test updates.",
                explanation="The change alters branch behavior without test updates.",
                suggested_follow_up="Add a regression test for the changed branch.",
            )
        ]
    )
    artifact_summary = summary
    if artifact_summary is None:
        artifact_summary = {
            "findings_present": "One medium-risk finding.",
            "no_findings": "No actionable findings in this review pass.",
            "manual_review_only": "The diff is too broad to assess reliably in this pass.",
        }[classification]
    return PublishableReviewArtifact(
        classification=classification,
        summary=artifact_summary,
        review_confidence=0.82 if classification == "findings_present" else 0.91,
        review_confidence_reason=(
            "The diff is small and the evidence is specific."
            if classification == "findings_present"
            else "The reviewed change is narrow and well supported."
        ),
        findings=findings,
        advisory_notes=advisory_notes or [],
        follow_up_lines=follow_up_lines or [],
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


def test_render_artifact_uses_one_sentence_for_runtime_failures() -> None:
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
    ) not in body


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
            follow_up_lines=["Follow-up review after the earlier bot pass on `abc123`."],
        ),
    )

    assert (
        "I took another look, and I don't see any actionable concerns in these changes now."
    ) in body


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
    assert review_client.inline_comments[0][0] == (
        "Missing test coverage.\n\nThe change alters branch behavior without test updates."
    )
    assert result.artifact is not None
    assert result.artifact.findings[0].inline_comment is not None
    assert result.artifact.findings[0].inline_comment.comment_id == "789"
    assert result.inline_comment_decisions is not None
    assert result.warning_message is None


def test_publish_artifact_uses_one_sentence_inline_comment_for_runtime_failures() -> None:
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
    assert review_client.inline_comments[0][0] == (
        "Unchecked access to `vehicle.types[0]` can raise `IndexError`."
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
        context=build_follow_up_context(),
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
        "to call them clear this time."
        in body
    )
    assert "The diff is too broad to assess reliably in this pass." in body
    assert "A human review is still needed before treating these changes as safe." in body
