from ai_sonar_bot.models.gitlab import MergeRequestNote
from ai_sonar_bot.models.review import (
    MergeRequestReviewContext,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from ai_sonar_bot.services.review_publisher import ReviewPublisher


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


def test_render_note_formats_findings_present() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing test coverage",
                    explanation="The change alters branch behavior without test updates.",
                    suggested_follow_up="Add a regression test for the changed branch.",
                )
            ],
        ),
    )

    assert "## AI Review Summary" in body
    assert "One medium-risk finding." in body
    assert "1. [medium] Missing test coverage (`src/service.py`)" in body
    assert "- Reviewed merge request: `!17`" in body
    assert "- Reviewed commit SHA: `abc123`" in body
    assert "- Files reviewed: 1" in body


def test_render_note_formats_no_findings() -> None:
    publisher = ReviewPublisher(FakeGitLabReviewClient())

    body = publisher.render_note(
        context=build_context(),
        review_result=ReviewResult(
            classification="no_findings",
            summary="No findings.",
            findings=[],
        ),
    )

    assert "No actionable findings in this review pass." in body
    assert "- Reviewed merge request: `!17`" in body
    assert "- Files reviewed: 1" in body
    assert "Notes:" not in body


def test_publish_sends_rendered_note_body() -> None:
    review_client = FakeGitLabReviewClient()
    publisher = ReviewPublisher(review_client)

    result = publisher.publish(
        project_id="123",
        merge_request_iid=17,
        context=build_context(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing test coverage",
                    explanation="The change alters branch behavior without test updates.",
                    suggested_follow_up="Add a regression test for the changed branch.",
                )
            ],
        ),
    )

    assert result.note is not None
    assert result.note.id == 55
    assert review_client.published_body is not None
    assert "Missing test coverage" in review_client.published_body
