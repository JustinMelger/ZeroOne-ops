from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.services.dashboard.dashboard_policy_action_service import (
    DashboardPolicyActionService,
)


def build_note(note_id: int, body: str, author_username: str = "operator") -> GitLabIssueNote:
    return GitLabIssueNote(
        id=note_id,
        body=body,
        author_username=author_username,
        created_at="2026-04-28T09:00:00.000Z",
    )


def test_parse_note_accepts_strict_supported_policy_commands() -> None:
    service = DashboardPolicyActionService()

    results = service.parse_notes(
        [
            build_note(1, "/zeroone policy show"),
            build_note(2, "/zeroone policy severity enable high"),
            build_note(3, "/zeroone policy severity disable medium"),
            build_note(4, "/zeroone policy issue-class exclude sonarqube / python:S3776"),
            build_note(5, "/zeroone policy issue-class include sonarqube / python:S3776"),
        ]
    )

    assert [result.accepted for result in results] == [True, True, True, True, True]
    assert [result.action.action_type for result in results if result.action is not None] == [
        "show_policy",
        "enable_severity",
        "disable_severity",
        "exclude_issue_class",
        "include_issue_class",
    ]


def test_parse_note_ignores_comments_without_policy_prefix() -> None:
    service = DashboardPolicyActionService()

    result = service.parse_note(build_note(1, "please enable high severity"))

    assert result.matched_prefix is False
    assert result.accepted is False
    assert result.action is None
    assert result.error is None


def test_parse_note_rejects_malformed_policy_command_safely() -> None:
    service = DashboardPolicyActionService()

    result = service.parse_note(build_note(1, "/zeroone policy severity maybe high"))

    assert result.matched_prefix is True
    assert result.accepted is False
    assert result.action is None
    assert result.error is not None


def test_parse_note_rejects_multiline_prefixed_markdown_as_non_command() -> None:
    service = DashboardPolicyActionService()

    result = service.parse_note(
        build_note(
            1,
            "/zeroone policy severity enable high\n- toggled a checkbox in the body too",
        )
    )

    assert result.matched_prefix is True
    assert result.accepted is False
    assert result.action is None

