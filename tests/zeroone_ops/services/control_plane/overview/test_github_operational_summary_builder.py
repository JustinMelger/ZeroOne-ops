from datetime import datetime

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
        _lookup_result(status="blocked", number=3, updated_at="2026-08-01T10:00:00+00:00"),
        _lookup_result(status="completed", number=4, updated_at="2026-08-03T10:00:00+00:00"),
        _lookup_result(status="dismissed", number=5, updated_at="2026-08-02T10:00:00+00:00"),
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
    assert view.active_change_requests[0].web_url == (
        "https://github.example.com/octo-org/octo-repo/pull/17"
    )
    assert [entry.status for entry in view.recent_outcomes] == ["completed", "dismissed"]


def test_builder_does_not_project_closed_linked_request_as_active() -> None:
    view = GitHubOperationalSummaryBuilder().build(
        work_items=[
            _lookup_result(
                status="completed",
                number=1,
                linked_change_request=True,
                updated_at="2026-08-03T10:00:00+00:00",
            )
        ],
        policy_issue_url=None,
        latest_finding_sync=None,
    )

    assert view.active_change_requests == []
    assert [entry.status for entry in view.recent_outcomes] == ["completed"]


def test_builder_excludes_closed_issue_with_nonterminal_embedded_state() -> None:
    result = _lookup_result(
        status="in_progress",
        number=1,
        linked_change_request=True,
    )
    closed_result = GitHubWorkItemLookupResult(
        issue=result.issue,
        work_item=result.work_item,
        is_open=False,
    )

    view = GitHubOperationalSummaryBuilder().build(
        work_items=[closed_result],
        policy_issue_url=None,
        latest_finding_sync=None,
    )

    assert view.work_item_counts == {
        "candidate": 0,
        "approved": 0,
        "in_progress": 0,
        "blocked": 0,
    }
    assert view.active_change_requests == []


def _lookup_result(
    *,
    status: str,
    number: int,
    linked_change_request: bool = False,
    updated_at: str | None = None,
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
            updated_at=(datetime.fromisoformat(updated_at) if updated_at is not None else None),
        ),
        work_item=work_item,
    )
