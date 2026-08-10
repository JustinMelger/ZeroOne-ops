"""Tests for GitLab dashboard policy-note authorization."""

from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.control_plane.policy.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
)


class FakeGitLabDashboardClient:
    def __init__(self, access_levels: dict[int, int | Exception]) -> None:
        self.access_levels = access_levels
        self.requested_user_ids: list[int] = []

    def get_project_member_access_level(self, *, project_id: str, user_id: int) -> int:
        del project_id
        self.requested_user_ids.append(user_id)
        result = self.access_levels[user_id]
        if isinstance(result, Exception):
            raise result
        return result


def build_note(*, note_id: int, author_id: int | None) -> GitLabIssueNote:
    return GitLabIssueNote(
        id=note_id,
        body="/zeroone policy severity disable high",
        author_id=author_id,
        author_username="operator",
    )


def test_authorized_notes_accepts_maintainers_and_owners() -> None:
    client = FakeGitLabDashboardClient({1: 40, 2: 50})
    service = GitLabPolicyNoteAuthorizationService(client)  # type: ignore[arg-type]

    notes = service.authorized_notes(
        project_id="123",
        notes=[build_note(note_id=1, author_id=1), build_note(note_id=2, author_id=2)],
    )

    assert [note.id for note in notes] == [1, 2]


def test_authorized_notes_ignores_developer_missing_identity_and_lookup_failures() -> None:
    client = FakeGitLabDashboardClient({1: 30, 2: GitLabClientError("unavailable")})
    service = GitLabPolicyNoteAuthorizationService(client)  # type: ignore[arg-type]

    notes = service.authorized_notes(
        project_id="123",
        notes=[
            build_note(note_id=1, author_id=1),
            build_note(note_id=2, author_id=2),
            build_note(note_id=3, author_id=None),
        ],
    )

    assert notes == []


def test_authorized_notes_caches_one_membership_lookup_per_author() -> None:
    client = FakeGitLabDashboardClient({1: 40})
    service = GitLabPolicyNoteAuthorizationService(client)  # type: ignore[arg-type]

    notes = service.authorized_notes(
        project_id="123",
        notes=[build_note(note_id=1, author_id=1), build_note(note_id=2, author_id=1)],
    )

    assert [note.id for note in notes] == [1, 2]
    assert client.requested_user_ids == [1]
