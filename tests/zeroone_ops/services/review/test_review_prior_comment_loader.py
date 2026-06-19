from zeroone_ops.models.gitlab import MergeRequestNote
from zeroone_ops.services.review.review_prior_comment_loader import (
    ChangeRequestPriorCommentLoader,
)


class FakeGitLabReviewClient:
    def __init__(self, notes: list[MergeRequestNote]) -> None:
        self.notes = notes

    def list_change_request_comments(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> list[MergeRequestNote]:
        del repository_id, change_request_number
        return self.notes


def build_note(
    *,
    note_id: int,
    reviewed_head_sha: str,
    created_at: str,
    author_username: str = "ai-sonar-bot",
    body_prefix: str = "Hi,\n\nHere are your review notes.\n\n",
) -> MergeRequestNote:
    body = body_prefix + (
        "<!-- ai-sonar-bot:review-note:v1\n"
        "{"
        f'"classification":"findings_present","findings":[],"findings_count":0,'
        f'"reviewed_head_sha":"{reviewed_head_sha}",'
        '"reviewed_change_request_number":17,'
        '"schema":"ai-sonar-bot/review-note/v1",'
        '"summary":"summary"'
        "}\n-->"
    )
    return MergeRequestNote(
        id=note_id,
        web_url=f"https://gitlab.example.com/group/project/-/merge_requests/17#note_{note_id}",
        body=body,
        author_username=author_username,
        created_at=created_at,
    )


def test_select_latest_prior_review_note_chooses_latest_earlier_note() -> None:
    service = ChangeRequestPriorCommentLoader(
        FakeGitLabReviewClient(
            [
                build_note(
                    note_id=10,
                    reviewed_head_sha="abc123",
                    created_at="2026-04-19T11:27:42.046Z",
                ),
                build_note(
                    note_id=11,
                    reviewed_head_sha="def456",
                    created_at="2026-04-19T11:29:42.046Z",
                ),
            ]
        )
    )

    result = service.select_latest_prior_review_note(
        repository_id="123",
        change_request_number=17,
        current_head_sha="ghi789",
    )

    assert result.selected_note is not None
    assert result.selected_note.id == 11
    assert result.considered_note_count == 2
    assert result.author_matched_note_count == 2
    assert result.machine_safe_note_count == 2
    assert result.parseable_note_count == 2
    assert result.current_sha_skipped_count == 0
    assert result.reason_code == "selected"
    assert result.message == "Selected latest earlier machine-safe bot review note."


def test_select_latest_prior_review_note_skips_current_head_sha() -> None:
    service = ChangeRequestPriorCommentLoader(
        FakeGitLabReviewClient(
            [
                build_note(
                    note_id=10,
                    reviewed_head_sha="abc123",
                    created_at="2026-04-19T11:27:42.046Z",
                ),
                build_note(
                    note_id=11,
                    reviewed_head_sha="ghi789",
                    created_at="2026-04-19T11:29:42.046Z",
                ),
            ]
        )
    )

    result = service.select_latest_prior_review_note(
        repository_id="123",
        change_request_number=17,
        current_head_sha="ghi789",
    )

    assert result.selected_note is not None
    assert result.selected_note.id == 10
    assert result.current_sha_skipped_count == 1


def test_select_latest_prior_review_note_ignores_notes_from_other_authors() -> None:
    service = ChangeRequestPriorCommentLoader(
        FakeGitLabReviewClient(
            [
                build_note(
                    note_id=12,
                    reviewed_head_sha="zzz999",
                    created_at="2026-04-19T11:31:42.046Z",
                    author_username="justin",
                ),
                build_note(
                    note_id=10,
                    reviewed_head_sha="abc123",
                    created_at="2026-04-19T11:27:42.046Z",
                ),
            ]
        )
    )

    result = service.select_latest_prior_review_note(
        repository_id="123",
        change_request_number=17,
        current_head_sha="ghi789",
    )

    assert result.selected_note is not None
    assert result.selected_note.id == 10
    assert result.author_matched_note_count == 1
    assert result.machine_safe_note_count == 1


def test_select_latest_prior_review_note_ignores_malformed_machine_safe_notes() -> None:
    service = ChangeRequestPriorCommentLoader(
        FakeGitLabReviewClient(
            [
                MergeRequestNote(
                    id=12,
                    body="<!-- ai-sonar-bot:review-note:v1\nnot-json\n-->",
                    author_username="ai-sonar-bot",
                    created_at="2026-04-19T11:30:42.046Z",
                ),
                build_note(
                    note_id=10,
                    reviewed_head_sha="abc123",
                    created_at="2026-04-19T11:27:42.046Z",
                ),
            ]
        )
    )

    result = service.select_latest_prior_review_note(
        repository_id="123",
        change_request_number=17,
        current_head_sha="ghi789",
    )

    assert result.selected_note is not None
    assert result.selected_note.id == 10
    assert result.machine_safe_note_count == 2
    assert result.parseable_note_count == 1


def test_select_latest_prior_review_note_returns_none_without_earlier_note() -> None:
    service = ChangeRequestPriorCommentLoader(
        FakeGitLabReviewClient(
            [
                MergeRequestNote(
                    id=12,
                    body="plain human note only",
                    author_username="ai-sonar-bot",
                    created_at="2026-04-19T11:30:42.046Z",
                ),
                build_note(
                    note_id=13,
                    reviewed_head_sha="ghi789",
                    created_at="2026-04-19T11:31:42.046Z",
                ),
            ]
        )
    )

    result = service.select_latest_prior_review_note(
        repository_id="123",
        change_request_number=17,
        current_head_sha="ghi789",
    )

    assert result.selected_note is None
    assert result.considered_note_count == 2
    assert result.author_matched_note_count == 2
    assert result.machine_safe_note_count == 1
    assert result.parseable_note_count == 1
    assert result.current_sha_skipped_count == 1
    assert result.reason_code == "only_current_sha_notes"
    assert result.message == (
        "No earlier machine-safe bot prior review note found on this change request."
    )


def test_select_latest_prior_review_note_allows_machine_safe_note_without_author_filter() -> None:
    service = ChangeRequestPriorCommentLoader(
        FakeGitLabReviewClient(
            [
                build_note(
                    note_id=12,
                    reviewed_head_sha="abc123",
                    created_at="2026-04-19T11:31:42.046Z",
                    author_username="custom-bot-user",
                )
            ]
        ),
        bot_author_username=None,
    )

    result = service.select_latest_prior_review_note(
        repository_id="123",
        change_request_number=17,
        current_head_sha="ghi789",
    )

    assert result.selected_note is not None
    assert result.selected_note.id == 12
    assert result.machine_safe_note_count == 1


def test_select_latest_prior_review_note_reports_no_author_match_reason() -> None:
    service = ChangeRequestPriorCommentLoader(
        FakeGitLabReviewClient(
            [
                build_note(
                    note_id=12,
                    reviewed_head_sha="abc123",
                    created_at="2026-04-19T11:31:42.046Z",
                    author_username="other-bot",
                )
            ]
        )
    )

    result = service.select_latest_prior_review_note(
        repository_id="123",
        change_request_number=17,
        current_head_sha="ghi789",
    )

    assert result.selected_note is None
    assert result.considered_note_count == 1
    assert result.author_matched_note_count == 0
    assert result.machine_safe_note_count == 0
    assert result.parseable_note_count == 0
    assert result.current_sha_skipped_count == 0
    assert result.reason_code == "no_author_match"


def test_select_latest_prior_review_note_reports_no_machine_safe_reason() -> None:
    service = ChangeRequestPriorCommentLoader(
        FakeGitLabReviewClient(
            [
                MergeRequestNote(
                    id=12,
                    body="plain operator note",
                    author_username="ai-sonar-bot",
                    created_at="2026-04-19T11:30:42.046Z",
                )
            ]
        )
    )

    result = service.select_latest_prior_review_note(
        repository_id="123",
        change_request_number=17,
        current_head_sha="ghi789",
    )

    assert result.selected_note is None
    assert result.considered_note_count == 1
    assert result.author_matched_note_count == 1
    assert result.machine_safe_note_count == 0
    assert result.parseable_note_count == 0
    assert result.current_sha_skipped_count == 0
    assert result.reason_code == "no_machine_safe_notes"
