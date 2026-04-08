from ai_sonar_bot.models.review import MergeRequestReviewCandidate, ReviewResult
from ai_sonar_bot.models.state import AppState, RepositoryState, RunStatus
from ai_sonar_bot.services.review_state_service import ReviewStateService
from ai_sonar_bot.services.state_store import StateStore


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


def build_merge_request() -> MergeRequestReviewCandidate:
    return MergeRequestReviewCandidate(
        iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
    )


def build_review_result() -> ReviewResult:
    return ReviewResult(
        classification="findings_present",
        summary="One finding.",
        findings=[],
    )


def test_mark_reviewed_persists_review_revision(tmp_path) -> None:
    store = StateStore(
        tmp_path / ".ai-sonar-bot-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    )
    service = ReviewStateService(state_store=store, state=build_state())
    record = service.start_run("run-1")

    summary = service.mark_reviewed(
        record=record,
        merge_request=build_merge_request(),
        review_result=build_review_result(),
        note_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
        dry_run=False,
    )

    assert summary.status == RunStatus.REVIEWED
    loaded = store.load()
    assert loaded.reviews["17:abc123"].status == "findings_present"
    assert loaded.reviews["17:abc123"].note_url is not None


def test_mark_reviewed_dry_run_does_not_persist_review_revision(tmp_path) -> None:
    store = StateStore(
        tmp_path / ".ai-sonar-bot-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    )
    service = ReviewStateService(state_store=store, state=build_state())
    record = service.start_run("run-1")

    summary = service.mark_reviewed(
        record=record,
        merge_request=build_merge_request(),
        review_result=ReviewResult(
            classification="no_findings",
            summary="No findings.",
            findings=[],
        ),
        note_url=None,
        dry_run=True,
    )

    assert summary.status == RunStatus.REVIEWED
    loaded = store.load()
    assert loaded.reviews == {}


def test_mark_reviewed_manual_review_only_uses_clear_summary_language(tmp_path) -> None:
    store = StateStore(
        tmp_path / ".ai-sonar-bot-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    )
    service = ReviewStateService(state_store=store, state=build_state())
    record = service.start_run("run-1")

    summary = service.mark_reviewed(
        record=record,
        merge_request=build_merge_request(),
        review_result=ReviewResult(
            classification="manual_review_only",
            summary="The available context was insufficient.",
            findings=[],
        ),
        note_url=None,
        dry_run=True,
    )

    assert summary.status == RunStatus.REVIEWED
    assert "Bot assessment was insufficient for a trustworthy review decision." in summary.message
    assert "The available context was insufficient." in summary.message
