from __future__ import annotations

from ai_sonar_bot.models.review import MergeRequestReviewCandidate
from ai_sonar_bot.services.mr_intake import MergeRequestIntakeService


class FakeGitLabReviewClient:
    def __init__(self, merge_requests: list[MergeRequestReviewCandidate]) -> None:
        self.merge_requests = merge_requests

    def list_open_merge_requests(self, *, project_id: str) -> list[MergeRequestReviewCandidate]:
        del project_id
        return self.merge_requests


def build_merge_request(
    iid: int,
    *,
    title: str = "feat: add review",
) -> MergeRequestReviewCandidate:
    return MergeRequestReviewCandidate(
        iid=iid,
        title=title,
        description="summary",
        source_branch=f"feature/{iid}",
        target_branch="main",
        web_url=f"https://gitlab.example.com/group/project/-/merge_requests/{iid}",
        head_sha=f"sha-{iid}",
    )


def test_select_merge_request_returns_first_open_candidate(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")

    result = MergeRequestIntakeService(
        review_client=FakeGitLabReviewClient(
            [build_merge_request(17), build_merge_request(18, title="feat: next review")]
        )
    ).select_merge_request()

    assert result.selected_merge_request is not None
    assert result.selected_merge_request.iid == 17
    assert result.merge_request_count == 2
    assert result.message == ""


def test_select_merge_request_returns_message_when_no_open_candidates(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")

    result = MergeRequestIntakeService(
        review_client=FakeGitLabReviewClient([])
    ).select_merge_request()

    assert result.selected_merge_request is None
    assert result.merge_request_count == 0
    assert "No reviewable GitLab merge request found" in result.message


def test_select_merge_request_reports_missing_gitlab_credentials(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("GITLAB_URL", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_PROJECT_ID", raising=False)
    monkeypatch.delenv("CI_PROJECT_ID", raising=False)
    monkeypatch.chdir(tmp_path)

    result = MergeRequestIntakeService().select_merge_request()

    assert result.selected_merge_request is None
    assert result.merge_request_count == 0
    assert result.message == "No merge request selected. GitLab credentials not configured."
