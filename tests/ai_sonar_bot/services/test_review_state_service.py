from ai_sonar_bot.models.review import (
    MergeRequestReviewCandidate,
    ReviewFinding,
    ReviewResult,
)
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
        review_confidence=0.76,
        review_confidence_reason="The finding is grounded in the reviewed diff.",
        findings=[
            ReviewFinding(
                severity="medium",
                file_path="src/service.py",
                title="Ordering regression",
                evidence="The diff removes explicit sorting before output.",
                explanation="This changes output semantics for callers.",
                suggested_follow_up="Restore deterministic ordering or document the change.",
            )
        ],
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
    assert loaded.reviews["17:abc123"].findings_count == 1
    assert loaded.reviews["17:abc123"].summary == "One finding."
    assert loaded.reviews["17:abc123"].findings[0].summary == "src/service.py: Ordering regression"
    assert loaded.reviews["17:abc123"].findings[0].severity == "medium"
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


def test_mark_reviewed_trims_prior_review_history_per_merge_request(tmp_path) -> None:
    store = StateStore(
        tmp_path / ".ai-sonar-bot-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    )
    state = build_state()
    service = ReviewStateService(
        state_store=store,
        state=state,
        max_prior_review_passes=2,
    )

    for run_id, head_sha in (("run-1", "sha-1"), ("run-2", "sha-2"), ("run-3", "sha-3")):
        record = service.start_run(run_id)
        service.mark_reviewed(
            record=record,
            merge_request=build_merge_request().model_copy(update={"head_sha": head_sha}),
            review_result=build_review_result(),
            note_url=None,
            dry_run=False,
        )

    loaded = store.load()
    assert "17:sha-1" not in loaded.reviews
    assert "17:sha-2" in loaded.reviews
    assert "17:sha-3" in loaded.reviews
