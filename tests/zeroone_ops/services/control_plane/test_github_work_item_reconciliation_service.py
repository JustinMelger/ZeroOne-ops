from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.github_work_item_reconciliation_service import (
    GitHubWorkItemReconciliationService,
)


def build_work_item() -> WorkItemState:
    return WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="in_progress",
        source=WorkItemSourceRef(
            source="sonarqube",
            source_item_key="AX123",
            repository_scope="octo-org/octo-repo",
        ),
        summary="Remediate Sonar issue AX123 in api.py",
        severity="high",
        file_path="src/api.py",
        line=42,
        linked_change_request=ChangeRequestRef(
            number=21,
            web_url="https://github.com/octo-org/octo-repo/pull/21",
        ),
    )


def test_reconcile_returns_completed_for_merged_pull_request() -> None:
    result = GitHubWorkItemReconciliationService().reconcile(
        work_item=build_work_item(),
        change_request_state=ChangeRequestState(
            iid=21,
            web_url="https://github.com/octo-org/octo-repo/pull/21",
            source_branch="zeroone-ops/fix",
            head_sha="abc123",
            state="merged",
        ),
    )

    assert result.action == "completed"
    assert result.work_item.status == "completed"
    assert "was merged" in result.message


def test_reconcile_returns_approved_for_closed_unmerged_pull_request() -> None:
    result = GitHubWorkItemReconciliationService().reconcile(
        work_item=build_work_item(),
        change_request_state=ChangeRequestState(
            iid=21,
            web_url="https://github.com/octo-org/octo-repo/pull/21",
            source_branch="zeroone-ops/fix",
            head_sha="abc123",
            state="closed",
        ),
    )

    assert result.action == "reopened"
    assert result.work_item.status == "approved"
    assert "closed without merge" in result.message


def test_reconcile_keeps_in_progress_for_open_pull_request() -> None:
    result = GitHubWorkItemReconciliationService().reconcile(
        work_item=build_work_item(),
        change_request_state=ChangeRequestState(
            iid=21,
            web_url="https://github.com/octo-org/octo-repo/pull/21",
            source_branch="zeroone-ops/fix",
            head_sha="abc123",
            state="opened",
        ),
    )

    assert result.action == "unchanged"
    assert result.work_item.status == "in_progress"
    assert "still open" in result.message


def test_reconcile_returns_updated_when_open_pull_request_changes_work_item_state() -> None:
    result = GitHubWorkItemReconciliationService().reconcile(
        work_item=build_work_item().model_copy(
            update={
                "status": "approved",
                "linked_change_request": ChangeRequestRef(
                    number=9,
                    web_url="https://github.com/octo-org/octo-repo/pull/9",
                ),
            }
        ),
        change_request_state=ChangeRequestState(
            iid=21,
            web_url="https://github.com/octo-org/octo-repo/pull/21",
            source_branch="zeroone-ops/fix",
            head_sha="abc123",
            state="opened",
        ),
    )

    assert result.action == "updated"
    assert result.work_item.status == "in_progress"
    assert result.work_item.linked_change_request is not None
    assert result.work_item.linked_change_request.number == 21
