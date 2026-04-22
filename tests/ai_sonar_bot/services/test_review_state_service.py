from ai_sonar_bot.models.review import (
    MergeRequestReviewCandidate,
    PriorReviewContext,
    ReviewFinding,
    ReviewResult,
)
from ai_sonar_bot.models.state import (
    AppState,
    MergeRequestReviewState,
    PriorReviewFindingState,
    RepositoryState,
    RunStatus,
)
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
                symbol="Service.run",
                issue_kind="ordering_regression",
                region_hint="return-order",
                title="Ordering regression",
                evidence="The diff removes explicit sorting before output.",
                explanation="This changes output semantics for callers.",
                suggested_follow_up="Restore deterministic ordering or document the change.",
            )
        ],
    )


def test_mark_reviewed_persists_review_revision(tmp_path) -> None:
    store = StateStore(
        tmp_path / ".zeroone-ops-state.json",
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
    assert (
        loaded.reviews["17:abc123"].findings[0].identity
        == "src/service.py::ordering_regression::service-run::return-order"
    )
    assert (
        loaded.reviews["17:abc123"].findings[0].legacy_identity == "src/service.py::order-regress"
    )
    assert loaded.reviews["17:abc123"].findings[0].summary == "src/service.py: Ordering regression"
    assert loaded.reviews["17:abc123"].findings[0].severity == "medium"
    assert loaded.reviews["17:abc123"].findings[0].symbol == "Service.run"
    assert loaded.reviews["17:abc123"].findings[0].issue_kind == "ordering_regression"
    assert loaded.reviews["17:abc123"].findings[0].region_hint == "return-order"
    assert loaded.reviews["17:abc123"].note_url is not None


def test_mark_reviewed_dry_run_does_not_persist_review_revision(tmp_path) -> None:
    store = StateStore(
        tmp_path / ".zeroone-ops-state.json",
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
        tmp_path / ".zeroone-ops-state.json",
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
        tmp_path / ".zeroone-ops-state.json",
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


def test_load_prior_review_context_returns_recent_passes_for_same_mr(tmp_path) -> None:
    store = StateStore(
        tmp_path / ".zeroone-ops-state.json",
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
            note_url=f"https://gitlab.example.com/note/{run_id}",
            dry_run=False,
        )

    prior_review_context = service.load_prior_review_context(
        mr_iid=17,
        current_head_sha="sha-3",
    )

    assert isinstance(prior_review_context, PriorReviewContext)
    assert prior_review_context.merge_request_iid == 17
    assert [review_pass.reviewed_head_sha for review_pass in prior_review_context.passes] == [
        "sha-2",
    ]
    assert prior_review_context.passes[0].classification == "findings_present"
    assert (
        prior_review_context.passes[0].findings[0].identity
        == "src/service.py::ordering_regression::service-run::return-order"
    )
    assert (
        prior_review_context.passes[0].findings[0].summary == "src/service.py: Ordering regression"
    )
    assert prior_review_context.passes[0].findings[0].symbol == "Service.run"
    assert prior_review_context.passes[0].findings[0].issue_kind == "ordering_regression"
    assert prior_review_context.passes[0].findings[0].region_hint == "return-order"


def test_mark_reviewed_persists_canonical_identity_with_human_summary(tmp_path) -> None:
    store = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    )
    service = ReviewStateService(state_store=store, state=build_state())
    record = service.start_run("run-1")

    service.mark_reviewed(
        record=record,
        merge_request=build_merge_request(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="Two findings.",
            findings=[
                ReviewFinding(
                    severity="high",
                    file_path="bnl_app/functions/vehicle_functions.py",
                    symbol="get_vehicle_details_short",
                    issue_kind="unconditional_exception",
                    region_hint="function-entry",
                    title="Unconditional exception breaks vehicle detail retrieval",
                    evidence="The diff inserts `raise ValueError` at the top of the helper.",
                    explanation="The helper now throws before any normal lookup logic runs.",
                    suggested_follow_up="Remove the unconditional exception.",
                ),
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    symbol="Service.run",
                    issue_kind="coverage_gap",
                    title="Missing test coverage",
                    evidence="The diff changes a branch without any test updates.",
                    explanation="The change alters branch behavior without regression coverage.",
                    suggested_follow_up="Add a regression test for the changed branch.",
                ),
            ],
        ),
        note_url=None,
        dry_run=False,
    )

    loaded = store.load()
    assert loaded.reviews["17:abc123"].findings[0].identity == (
        "bnl_app/functions/vehicle_functions.py::unconditional_exception::get_vehicle_details_short::function-entry"
    )
    assert loaded.reviews["17:abc123"].findings[0].summary == (
        "bnl_app/functions/vehicle_functions.py: "
        "Unconditional exception breaks vehicle detail retrieval"
    )
    assert loaded.reviews["17:abc123"].findings[1].identity == (
        "src/service.py::coverage_gap::service-run"
    )
    assert loaded.reviews["17:abc123"].findings[1].summary == (
        "src/service.py: Missing test coverage"
    )
    assert loaded.reviews["17:abc123"].findings[0].symbol == "get_vehicle_details_short"
    assert loaded.reviews["17:abc123"].findings[0].issue_kind == "unconditional_exception"
    assert loaded.reviews["17:abc123"].findings[0].region_hint == "function-entry"
    assert loaded.reviews["17:abc123"].findings[1].symbol == "Service.run"
    assert loaded.reviews["17:abc123"].findings[1].issue_kind == "coverage_gap"
    assert loaded.reviews["17:abc123"].findings[1].region_hint is None


def test_load_prior_review_context_preserves_mixed_new_and_legacy_finding_state(tmp_path) -> None:
    store = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    )
    state = build_state()
    state.reviews["17:sha-2"] = MergeRequestReviewState(
        mr_iid=17,
        head_sha="sha-2",
        status="findings_present",
        last_run_id="run-2",
        findings_count=2,
        summary="Two findings.",
        findings=[
            PriorReviewFindingState(
                identity="src/service.py::order-regress",
                summary="src/service.py: Ordering regression",
                severity="medium",
                symbol="Service.run",
                issue_kind="ordering_regression",
                region_hint="return-order",
            ),
            PriorReviewFindingState(
                summary="Legacy helper concern",
                severity="low",
            ),
        ],
    )
    service = ReviewStateService(
        state_store=store,
        state=state,
        max_prior_review_passes=2,
    )

    prior_review_context = service.load_prior_review_context(
        mr_iid=17,
        current_head_sha="sha-3",
    )

    assert isinstance(prior_review_context, PriorReviewContext)
    assert prior_review_context.passes[0].findings[0].identity == "src/service.py::order-regress"
    assert (
        prior_review_context.passes[0].findings[0].summary == "src/service.py: Ordering regression"
    )
    assert prior_review_context.passes[0].findings[0].symbol == "Service.run"
    assert prior_review_context.passes[0].findings[0].issue_kind == "ordering_regression"
    assert prior_review_context.passes[0].findings[0].region_hint == "return-order"
    assert prior_review_context.passes[0].findings[1].identity is None
    assert prior_review_context.passes[0].findings[1].summary == "Legacy helper concern"
