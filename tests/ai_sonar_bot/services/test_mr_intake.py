from __future__ import annotations

from ai_sonar_bot.models.review import MergeRequestReviewCandidate
from ai_sonar_bot.models.state import AppState, MergeRequestReviewState, RepositoryState
from ai_sonar_bot.services.mr_intake import MergeRequestIntakeService
from ai_sonar_bot.services.mr_selector import build_review_revision_key


class FakeGitLabReviewClient:
    def __init__(self, merge_requests: list[MergeRequestReviewCandidate]) -> None:
        self.merge_requests = merge_requests
        self.requested_merge_request_iid: int | None = None

    def list_open_merge_requests(self, *, project_id: str) -> list[MergeRequestReviewCandidate]:
        del project_id
        return self.merge_requests

    def get_merge_request(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> MergeRequestReviewCandidate:
        del project_id
        self.requested_merge_request_iid = merge_request_iid
        for merge_request in self.merge_requests:
            if merge_request.iid == merge_request_iid:
                return merge_request
        raise AssertionError(f"Unexpected merge request IID requested: {merge_request_iid}")


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


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


def test_select_merge_request_returns_first_open_candidate(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")

    result = MergeRequestIntakeService(
        review_client=FakeGitLabReviewClient(
            [build_merge_request(17), build_merge_request(18, title="feat: next review")]
        )
    ).select_merge_request(state=build_state())

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
    ).select_merge_request(state=build_state())

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

    result = MergeRequestIntakeService().select_merge_request(state=build_state())

    assert result.selected_merge_request is None
    assert result.merge_request_count == 0
    assert result.message == "No merge request selected. GitLab credentials not configured."


def test_select_merge_request_skips_already_reviewed_revision(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    state = build_state()
    state.reviews[build_review_revision_key(mr_iid=17, head_sha="sha-17")] = (
        MergeRequestReviewState(
            mr_iid=17,
            head_sha="sha-17",
            status="published",
            last_run_id="run-1",
        )
    )

    result = MergeRequestIntakeService(
        review_client=FakeGitLabReviewClient([build_merge_request(17), build_merge_request(18)])
    ).select_merge_request(state=state)

    assert result.selected_merge_request is not None
    assert result.selected_merge_request.iid == 18


def test_select_merge_request_reports_when_all_open_mrs_are_already_reviewed(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    state = build_state()
    state.reviews[build_review_revision_key(mr_iid=17, head_sha="sha-17")] = (
        MergeRequestReviewState(
            mr_iid=17,
            head_sha="sha-17",
            status="published",
            last_run_id="run-1",
        )
    )

    result = MergeRequestIntakeService(
        review_client=FakeGitLabReviewClient([build_merge_request(17)])
    ).select_merge_request(state=state)

    assert result.selected_merge_request is None
    assert result.merge_request_count == 1
    assert "already reviewed for their current head SHA" in result.message


def test_select_merge_request_prefers_triggering_merge_request_iid_in_ci(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "18")
    review_client = FakeGitLabReviewClient([build_merge_request(17), build_merge_request(18)])

    result = MergeRequestIntakeService(review_client=review_client).select_merge_request(
        state=build_state()
    )

    assert result.selected_merge_request is not None
    assert result.selected_merge_request.iid == 18
    assert result.merge_request_count == 1
    assert review_client.requested_merge_request_iid == 18
