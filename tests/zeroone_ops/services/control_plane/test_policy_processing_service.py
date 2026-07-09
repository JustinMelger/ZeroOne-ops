from zeroone_ops.models.policy import (
    PolicyCommentSource,
    PolicySeverityStateEntry,
    PolicyState,
)
from zeroone_ops.services.control_plane.policy_processing_service import (
    PolicyProcessingService,
)


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


def test_process_replays_comments_and_reports_counts() -> None:
    service = PolicyProcessingService()

    result = service.process(
        initial_policy_state=PolicyState(
            severity_policy=[
                PolicySeverityStateEntry(severity="low", enabled=True),
                PolicySeverityStateEntry(severity="medium", enabled=True),
                PolicySeverityStateEntry(severity="high", enabled=True),
            ]
        ),
        sources=[
            build_source(1, "/zeroone policy severity disable high"),
            build_source(2, "/zeroone policy severity maybe high"),
            build_source(3, "ordinary comment"),
        ],
    )

    severity_by_name = {
        entry.severity: entry for entry in result.resolved_policy_state.severity_policy
    }
    assert result.source_count == 3
    assert result.matched_prefix_count == 2
    assert result.accepted_action_count == 1
    assert result.rejected_prefix_count == 1
    assert severity_by_name["high"].enabled is False
    assert severity_by_name["high"].comment_id == 1
