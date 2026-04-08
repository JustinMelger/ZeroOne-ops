from ai_sonar_bot.models.dashboard import DashboardItem
from ai_sonar_bot.models.gitlab import GitLabMergeRequestState
from ai_sonar_bot.providers.gitlab_client import GitLabClientError
from ai_sonar_bot.services.dashboard_reconciliation_service import (
    DashboardReconciliationService,
    merge_request_iid_from_url,
)


def build_item(
    *,
    merge_request_url: str = "https://gitlab.example.com/group/project/-/merge_requests/7",
    branch_name: str = "ai-sonar/issue-1/service",
    commit_sha: str = "abc123",
) -> DashboardItem:
    return DashboardItem(
        id="sonar:1",
        source="sonarqube",
        type="code_smell_fix",
        status="mr_opened",
        title="Fix issue",
        summary="Fix the issue safely.",
        priority="low",
        source_reference="issue-1",
        file="src/service.py",
        line=10,
        rule="python:S1125",
        severity="LOW",
        merge_request_url=merge_request_url,
        branch_name=branch_name,
        commit_sha=commit_sha,
    )


class FakeReviewClient:
    def __init__(self, merge_request_state: GitLabMergeRequestState) -> None:
        self.merge_request_state = merge_request_state

    def get_merge_request_state(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> GitLabMergeRequestState:
        del project_id, merge_request_iid
        return self.merge_request_state


class FailingReviewClient:
    def get_merge_request_state(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> GitLabMergeRequestState:
        del project_id, merge_request_iid
        raise GitLabClientError("GitLab returned 404")


def test_merge_request_iid_from_url_extracts_iid() -> None:
    assert (
        merge_request_iid_from_url("https://gitlab.example.com/group/project/-/merge_requests/7")
        == 7
    )


def test_decide_returns_done_for_merged_merge_request() -> None:
    decision = DashboardReconciliationService(
        FakeReviewClient(
            GitLabMergeRequestState(
                iid=7,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/7",
                source_branch="ai-sonar/issue-1/service",
                head_sha="abc123",
                state="merged",
            )
        )
    ).decide(project_id="123", item=build_item())

    assert decision.action == "done"
    assert "was merged" in decision.message


def test_decide_returns_open_for_closed_merge_request_with_matching_traceability() -> None:
    decision = DashboardReconciliationService(
        FakeReviewClient(
            GitLabMergeRequestState(
                iid=7,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/7",
                source_branch="ai-sonar/issue-1/service",
                head_sha="abc123",
                state="closed",
            )
        )
    ).decide(project_id="123", item=build_item())

    assert decision.action == "open"
    assert "closed without merge" in decision.message


def test_decide_returns_done_for_closed_merge_request_when_dashboard_marks_item_inactive() -> None:
    decision = DashboardReconciliationService(
        FakeReviewClient(
            GitLabMergeRequestState(
                iid=7,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/7",
                source_branch="ai-sonar/issue-1/service",
                head_sha="abc123",
                state="closed",
            )
        )
    ).decide(
        project_id="123",
        item=build_item().model_copy(update={"upstream_active": False}),
    )

    assert decision.action == "done"
    assert "no longer active" in decision.message


def test_decide_returns_failed_for_closed_merge_request_with_mismatched_traceability() -> None:
    decision = DashboardReconciliationService(
        FakeReviewClient(
            GitLabMergeRequestState(
                iid=7,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/7",
                source_branch="other-branch",
                head_sha="different",
                state="closed",
            )
        )
    ).decide(project_id="123", item=build_item())

    assert decision.action == "failed"
    assert "no longer matches" in decision.message


def test_decide_returns_failed_when_merge_request_metadata_is_inaccessible() -> None:
    decision = DashboardReconciliationService(FailingReviewClient()).decide(
        project_id="123",
        item=build_item(),
    )

    assert decision.action == "failed"
    assert "metadata is inaccessible" in decision.message
