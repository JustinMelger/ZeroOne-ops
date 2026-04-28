from zeroone_ops.models.dashboard import DashboardPolicyState
from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.services.dashboard.dashboard_policy_action_service import (
    DashboardPolicyActionService,
)


def build_note(
    note_id: int,
    body: str,
    author_username: str = "operator",
    *,
    created_at: str = "2026-04-28T09:00:00.000Z",
) -> GitLabIssueNote:
    return GitLabIssueNote(
        id=note_id,
        body=body,
        author_username=author_username,
        created_at=created_at,
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


def test_apply_actions_uses_latest_severity_command_by_created_at() -> None:
    service = DashboardPolicyActionService()

    policy_state = service.apply_actions(
        policy_state=DashboardPolicyState(),
        notes=[
            build_note(
                1,
                "/zeroone policy severity disable high",
                created_at="2026-04-28T09:00:00.000Z",
            ),
            build_note(
                2,
                "/zeroone policy severity enable high",
                created_at="2026-04-28T09:01:00.000Z",
            ),
        ],
    )

    severity_by_name = {entry.severity: entry for entry in policy_state.severity_policy}
    assert severity_by_name["high"].enabled is True


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


def test_apply_actions_uses_note_id_when_created_at_matches() -> None:
    service = DashboardPolicyActionService()

    policy_state = service.apply_actions(
        policy_state=DashboardPolicyState(),
        notes=[
            build_note(10, "/zeroone policy severity disable high"),
            build_note(11, "/zeroone policy severity enable high"),
        ],
    )

    severity_by_name = {entry.severity: entry for entry in policy_state.severity_policy}
    assert severity_by_name["high"].enabled is True


def test_apply_actions_uses_latest_issue_class_command_by_created_at() -> None:
    service = DashboardPolicyActionService()

    policy_state = service.apply_actions(
        policy_state=DashboardPolicyState(),
        notes=[
            build_note(
                1,
                "/zeroone policy issue-class exclude sonarqube / python:S3776",
                created_at="2026-04-28T09:00:00.000Z",
            ),
            build_note(
                2,
                "/zeroone policy issue-class include sonarqube / python:S3776",
                created_at="2026-04-28T09:01:00.000Z",
            ),
        ],
    )

    assert policy_state.issue_class_exclusions == []


def test_apply_actions_uses_note_id_for_issue_class_commands_when_created_at_matches() -> None:
    service = DashboardPolicyActionService()

    policy_state = service.apply_actions(
        policy_state=DashboardPolicyState(),
        notes=[
            build_note(10, "/zeroone policy issue-class exclude sonarqube / python:S3776"),
            build_note(11, "/zeroone policy issue-class include sonarqube / python:S3776"),
        ],
    )

    assert policy_state.issue_class_exclusions == []


def test_apply_actions_keeps_unrelated_policy_entries_unchanged() -> None:
    service = DashboardPolicyActionService()

    policy_state = service.apply_actions(
        policy_state=DashboardPolicyState(),
        notes=[
            build_note(1, "/zeroone policy issue-class exclude sonarqube / python:S3776"),
            build_note(2, "/zeroone policy severity disable high"),
        ],
    )

    assert len(policy_state.issue_class_exclusions) == 1
    assert policy_state.issue_class_exclusions[0].issue_key == "python:S3776"
    severity_by_name = {entry.severity: entry for entry in policy_state.severity_policy}
    assert severity_by_name["high"].enabled is False


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
