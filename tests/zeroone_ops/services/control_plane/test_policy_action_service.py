from zeroone_ops.models.policy import PolicyCommentSource, PolicyState
from zeroone_ops.services.control_plane.policy_action_service import PolicyActionService


def build_source(
    comment_id: int,
    body: str,
    author_username: str = "operator",
    *,
    created_at: str = "2026-04-28T09:00:00.000Z",
) -> PolicyCommentSource:
    return PolicyCommentSource(
        id=comment_id,
        body=body,
        author_username=author_username,
        created_at=created_at,
    )


def test_parse_source_accepts_supported_policy_commands() -> None:
    service = PolicyActionService()

    results = service.parse_sources(
        [
            build_source(1, "/zeroone policy show"),
            build_source(2, "/zeroone policy severity enable high"),
            build_source(3, "/zeroone policy issue-class exclude sonarqube / python:S3776"),
        ]
    )

    assert [result.accepted for result in results] == [True, True, True]
    assert [result.action.action_type for result in results if result.action is not None] == [
        "show_policy",
        "enable_severity",
        "exclude_issue_class",
    ]


def test_apply_actions_replays_latest_command_by_created_at() -> None:
    service = PolicyActionService()

    policy_state = service.apply_actions(
        policy_state=PolicyState(),
        sources=[
            build_source(
                1,
                "/zeroone policy severity disable high",
                created_at="2026-04-28T09:00:00.000Z",
            ),
            build_source(
                2,
                "/zeroone policy severity enable high",
                created_at="2026-04-28T09:01:00.000Z",
            ),
        ],
    )

    severity_by_name = {entry.severity: entry for entry in policy_state.severity_policy}
    assert severity_by_name["high"].enabled is True
    assert severity_by_name["high"].comment_id == 2


def test_apply_actions_ignores_unparsable_created_at_metadata() -> None:
    service = PolicyActionService()

    policy_state = service.apply_actions(
        policy_state=PolicyState(),
        sources=[
            build_source(
                1,
                "/zeroone policy severity disable high",
                created_at="not-a-timestamp",
            ),
        ],
    )

    severity_by_name = {entry.severity: entry for entry in policy_state.severity_policy}
    assert severity_by_name["high"].enabled is False
    assert severity_by_name["high"].comment_id == 1
    assert severity_by_name["high"].updated_at is None


def test_apply_actions_orders_valid_offset_timestamps_by_actual_time() -> None:
    service = PolicyActionService()

    policy_state = service.apply_actions(
        policy_state=PolicyState(),
        sources=[
            build_source(
                1,
                "/zeroone policy severity enable high",
                created_at="2026-04-28T10:00:00+01:00",
            ),
            build_source(
                2,
                "/zeroone policy severity disable high",
                created_at="2026-04-28T09:30:00Z",
            ),
        ],
    )

    severity_by_name = {entry.severity: entry for entry in policy_state.severity_policy}
    assert severity_by_name["high"].enabled is False
    assert severity_by_name["high"].comment_id == 2
