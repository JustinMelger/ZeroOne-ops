import json

from zeroone_ops.models.gitlab import MergeRequestNote
from zeroone_ops.models.review import (
    MergeRequestReviewContext,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewPass,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    ReviewFileContext,
)
from zeroone_ops.services.review.review_publisher import ReviewPublisher


def extract_machine_safe_payload(body: str) -> dict[str, object]:
    start_marker = "<!-- ai-sonar-bot:review-note:v1\n"
    end_marker = "\n-->"
    start = body.index(start_marker) + len(start_marker)
    end = body.index(end_marker, start)
    return json.loads(body[start:end])


def build_context() -> MergeRequestReviewContext:
    return MergeRequestReviewContext(
        mr_iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )


def build_follow_up_context() -> MergeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                merge_request_iid=17,
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


def build_ambiguous_follow_up_context() -> MergeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                merge_request_iid=17,
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


def build_mixed_ambiguity_follow_up_context() -> MergeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                merge_request_iid=17,
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


def build_variant_title_follow_up_context() -> MergeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "ghi789",
            "prior_review_context": PriorReviewContext(
                merge_request_iid=17,
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


def build_artifact(
    *,
    classification: str = "findings_present",
    summary: str | None = None,
    follow_up_lines: list[str] | None = None,
) -> PublishableReviewArtifact:
    findings = (
        []
        if classification != "findings_present"
        else [
            PublishableReviewFinding(
                severity="medium",
                file_path="src/service.py",
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
        follow_up_lines=follow_up_lines or [],
    )


def test_render_artifact_formats_findings_present() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_context(),
        artifact=build_artifact(),
    )

    assert body.startswith("Hi,\n\nHere are your review notes.")
    assert "One medium-risk finding." in body
    assert "Review confidence: 0.82" in body
    assert "Reason: The diff is small and the evidence is specific." in body
    assert "1. [medium] Missing test coverage (`src/service.py`)" in body
    assert (
        "Evidence: The diff changes `value = 1` to `value = 2` without any test updates."
    ) in body
    assert "- Reviewed merge request: `!17`" in body
    assert "- Reviewed commit SHA: `abc123`" in body
    assert "- Files reviewed: 1" in body

    payload = extract_machine_safe_payload(body)
    assert payload["schema"] == "ai-sonar-bot/review-note/v1"
    assert payload["reviewed_merge_request_iid"] == 17
    assert payload["reviewed_head_sha"] == "abc123"
    assert payload["classification"] == "findings_present"
    assert payload["findings_count"] == 1
    assert payload["findings"] == [
        {
            "file_path": "src/service.py",
            "issue_kind": None,
            "region_hint": None,
            "severity": "medium",
            "summary": "src/service.py: Missing test coverage",
            "symbol": None,
            "title": "Missing test coverage",
        }
    ]


def test_render_artifact_formats_no_findings() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_context(),
        artifact=build_artifact(classification="no_findings"),
    )

    assert "No actionable findings in this review pass." in body
    assert body.startswith("Hi,\n\nHere are your review notes.")
    assert "Review confidence: 0.91" in body
    assert "- Reviewed merge request: `!17`" in body
    assert "- Files reviewed: 1" in body
    assert "Notes:" not in body

    payload = extract_machine_safe_payload(body)
    assert payload["classification"] == "no_findings"
    assert payload["findings_count"] == 0
    assert payload["findings"] == []


def test_publish_artifact_sends_rendered_note_body() -> None:
    review_client = FakeGitLabReviewClient()
    publisher = ReviewPublisher(review_client)

    result = publisher.publish_artifact(
        project_id="123",
        merge_request_iid=17,
        context=build_context(),
        artifact=build_artifact(),
    )

    assert result.note is not None
    assert result.note.id == 55
    assert review_client.published_body is not None
    assert "Missing test coverage" in review_client.published_body


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

    assert "Follow-up review after the earlier bot pass on `abc123`." in body
    assert "An earlier concern from the last pass still appears unresolved." in body


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

    assert (
        "This pass may overlap with an earlier concern, but the overlap is not "
        "fully clear from the current changes." in body
    )


def test_render_artifact_omits_follow_up_wording_when_missing() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_artifact(
        context=build_follow_up_context(),
        artifact=build_artifact(),
    )

    assert "Follow-up review after the earlier bot pass" not in body
    assert "still appears unresolved" not in body


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

    assert (
        "This pass may still relate to an earlier concern, but the current review "
        "was not confident enough to verify continuity fully." in body
    )
    assert "introduces a new concern" not in body
    assert "no longer appears present" not in body
