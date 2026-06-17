from __future__ import annotations

from zeroone_ops.models.review import ChangeRequestReviewCandidate
from zeroone_ops.models.state import AppState, ChangeRequestReviewState, RepositoryState
from zeroone_ops.services.review.change_request_intake import ChangeRequestIntakeService
from zeroone_ops.services.review.change_request_selector import build_review_revision_key


class FakeGitLabReviewClient:
    def __init__(self, change_requests: list[ChangeRequestReviewCandidate]) -> None:
        self.change_requests = change_requests
        self.requested_change_request_number: int | None = None

    def list_open_merge_requests(self, *, project_id: str) -> list[ChangeRequestReviewCandidate]:
        del project_id
        return self.merge_requests

    def get_change_request(
        self,
        *,
        project_id: str,
        change_request_number: int,
    ) -> ChangeRequestReviewCandidate:
        return self.get_merge_request(
            project_id=project_id,
            merge_request_iid=change_request_number,
        )

    def get_merge_request(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> ChangeRequestReviewCandidate:
        del project_id
        self.requested_change_request_number = merge_request_iid
        for change_request in self.change_requests:
            if change_request.change_request_number == merge_request_iid:
                return change_request
        raise AssertionError(f"Unexpected change request number requested: {merge_request_iid}")


def build_change_request(
    number: int,
    *,
    title: str = "feat: add review",
) -> ChangeRequestReviewCandidate:
    return ChangeRequestReviewCandidate(
        change_request_number=number,
        title=title,
        description="summary",
        source_branch=f"feature/{number}",
        target_branch="main",
        web_url=f"https://gitlab.example.com/group/project/-/merge_requests/{number}",
        head_sha=f"sha-{number}",
    )


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


def test_select_change_request_requires_ci_change_request_number(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")

    result = ChangeRequestIntakeService(
        review_client=FakeGitLabReviewClient(
            [build_change_request(17), build_change_request(18, title="feat: next review")]
        )
    ).select_change_request(state=build_state())

    assert result.selected_change_request is None
    assert result.change_request_count == 0
    assert result.message == (
        "No change request selected. Review runs are only supported for "
        "CI-triggered change requests."
    )


def test_select_change_request_reports_invalid_ci_change_request_number(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "abc")

    result = ChangeRequestIntakeService(
        review_client=FakeGitLabReviewClient([])
    ).select_change_request(state=build_state())

    assert result.selected_change_request is None
    assert result.change_request_count == 0
    assert result.message == "No change request selected. CI change request number is invalid."


def test_select_change_request_reports_missing_gitlab_credentials(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("GITLAB_URL", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_PROJECT_ID", raising=False)
    monkeypatch.delenv("CI_PROJECT_ID", raising=False)
    monkeypatch.chdir(tmp_path)

    result = ChangeRequestIntakeService().select_change_request(state=build_state())

    assert result.selected_change_request is None
    assert result.change_request_count == 0
    assert result.message == (
        "No change request selected. Review platform credentials not configured."
    )


def test_select_change_request_reports_already_reviewed_revision_for_targeted_ci_change_request(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    state = build_state()
    state.reviews[build_review_revision_key(change_request_number=17, head_sha="sha-17")] = (
        ChangeRequestReviewState(
            change_request_number=17,
            head_sha="sha-17",
            status="findings_present",
            last_run_id="run-1",
        )
    )

    result = ChangeRequestIntakeService(
        review_client=FakeGitLabReviewClient([build_change_request(17), build_change_request(18)])
    ).select_change_request(state=state)

    assert result.selected_change_request is not None
    assert result.selected_change_request.change_request_number == 17
    assert result.selected_skip_reason == "already_reviewed_revision"


def test_select_change_request_reports_when_all_open_requests_are_already_reviewed(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    state = build_state()
    state.reviews[build_review_revision_key(change_request_number=17, head_sha="sha-17")] = (
        ChangeRequestReviewState(
            change_request_number=17,
            head_sha="sha-17",
            status="findings_present",
            last_run_id="run-1",
        )
    )

    result = ChangeRequestIntakeService(
        review_client=FakeGitLabReviewClient([build_change_request(17)])
    ).select_change_request(state=state)

    assert result.selected_change_request is not None
    assert result.selected_change_request.change_request_number == 17
    assert result.change_request_count == 1
    assert result.message == ""
    assert result.selected_skip_reason == "already_reviewed_revision"


def test_select_change_request_skips_manual_review_only_revision(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    state = build_state()
    state.reviews[build_review_revision_key(change_request_number=17, head_sha="sha-17")] = (
        ChangeRequestReviewState(
            change_request_number=17,
            head_sha="sha-17",
            status="manual_review_only",
            last_run_id="run-1",
        )
    )

    result = ChangeRequestIntakeService(
        review_client=FakeGitLabReviewClient([build_change_request(17)])
    ).select_change_request(state=state)

    assert result.selected_change_request is not None
    assert result.selected_change_request.change_request_number == 17
    assert result.selected_skip_reason == "already_reviewed_revision"


def test_select_change_request_prefers_triggering_ci_change_request_number(monkeypatch) -> None:
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "18")
    review_client = FakeGitLabReviewClient([build_change_request(17), build_change_request(18)])

    result = ChangeRequestIntakeService(review_client=review_client).select_change_request(
        state=build_state()
    )

    assert result.selected_change_request is not None
    assert result.selected_change_request.change_request_number == 18
    assert result.change_request_count == 1
    assert review_client.requested_change_request_number == 18
