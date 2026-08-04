from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.overview.github_operational_summary_builder import (
    GitHubOperationalSummaryBuilder,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)


def test_builder_projects_open_state_active_prs_and_bounded_outcomes() -> None:
    work_items = [
        _lookup_result(status="approved", number=1),
        _lookup_result(status="in_progress", number=2, linked_change_request=True),
        _lookup_result(status="blocked", number=3),
        _lookup_result(status="completed", number=4),
        _lookup_result(status="dismissed", number=5),
    ]

    view = GitHubOperationalSummaryBuilder().build(
        work_items=work_items,
        policy_issue_url="https://github.example.com/octo-org/octo-repo/issues/99",
        latest_finding_sync=None,
        recent_outcome_limit=2,
    )

    assert view.work_item_counts == {
        "candidate": 0,
        "approved": 1,
        "in_progress": 1,
        "blocked": 1,
    }
    assert [entry.status for entry in view.active_change_requests] == ["in_progress"]
    assert [entry.status for entry in view.recent_outcomes] == ["blocked", "completed"]


def _lookup_result(
    *,
    status: str,
    number: int,
    linked_change_request: bool = False,
) -> GitHubWorkItemLookupResult:
    work_item = WorkItemState(
        work_item_id=f"work-{number}",
        kind="remediation",
        status=status,  # type: ignore[arg-type]
        source=WorkItemSourceRef(source="ruff-sarif", source_item_key=f"finding-{number}"),
        summary=f"Finding {number}",
        linked_change_request=(
            ChangeRequestRef(
                number=17,
                web_url="https://github.example.com/octo-org/octo-repo/pull/17",
            )
            if linked_change_request
            else None
        ),
    )
    return GitHubWorkItemLookupResult(
        issue=GitHubIssueInfo(
            id=number,
            number=number,
            web_url=f"https://github.example.com/octo-org/octo-repo/issues/{number}",
            title=f"ZeroOne Ops: item {number}",
            body="",
        ),
        work_item=work_item,
    )
