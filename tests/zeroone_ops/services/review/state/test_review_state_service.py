from datetime import UTC, datetime

from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    PrecisionAcceptedFinding,
    PrecisionReviewDecision,
    PriorReviewContext,
    PriorReviewInlineComment,
    PublishableReviewArtifact,
    PublishableReviewFinding,
)
from zeroone_ops.models.state import (
    AppState,
    ChangeRequestReviewState,
    PriorReviewFindingState,
    RepositoryState,
    RunStatus,
)
from zeroone_ops.services.review.pipeline.review_reconciled_decision_builder import (
    build_reconciled_review_decision,
)
from zeroone_ops.services.review.state.review_state_service import ReviewStateService
from zeroone_ops.services.shared.state_store import StateStore


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


def build_merge_request() -> ChangeRequestReviewCandidate:
    return ChangeRequestReviewCandidate(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
    )


def build_artifact() -> PublishableReviewArtifact:
    return PublishableReviewArtifact(
        classification="findings_present",
        summary="One finding.",
        follow_up_lines=["Follow-up review after the earlier bot pass on `abc123`."],
        review_confidence=0.76,
        review_confidence_reason="The finding is grounded in the reviewed diff.",
        findings=[
            PublishableReviewFinding(
                severity="medium",
                file_path="src/service.py",
                stable_identity="src/service.py::ordering_regression::service-run::return-order",
                legacy_identity="src/service.py::order-regress",
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
        artifact=build_artifact(),
        note_id=55,
        note_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
        projection_retry_pending=True,
        projection_retry_warning="Review projection warning: projection boom",
        dry_run=False,
    )

    assert summary.status == RunStatus.REVIEWED
    loaded = store.load()
    assert loaded.reviews["17:abc123"].status == "findings_present"
    assert loaded.reviews["17:abc123"].findings_count == 1
    assert loaded.reviews["17:abc123"].summary == "One finding."
    assert loaded.reviews["17:abc123"].follow_up_lines == [
        "Follow-up review after the earlier bot pass on `abc123`."
    ]
    assert (
        loaded.reviews["17:abc123"].findings[0].identity
        == "src/service.py::ordering_regression::service-run::return-order"
    )
    assert (
        loaded.reviews["17:abc123"].findings[0].legacy_identity == "src/service.py::order-regress"
    )
    assert loaded.reviews["17:abc123"].findings[0].summary == "src/service.py: Ordering regression"
    assert loaded.reviews["17:abc123"].findings[0].severity == "medium"
    assert loaded.reviews["17:abc123"].findings[0].file_path == "src/service.py"
    assert loaded.reviews["17:abc123"].findings[0].title == "Ordering regression"
    assert loaded.reviews["17:abc123"].findings[0].symbol == "Service.run"
    assert loaded.reviews["17:abc123"].findings[0].issue_kind == "ordering_regression"
    assert loaded.reviews["17:abc123"].findings[0].region_hint == "return-order"
    assert loaded.reviews["17:abc123"].note_id == 55
    assert loaded.reviews["17:abc123"].note_url is not None
    assert loaded.reviews["17:abc123"].projection_retry_pending is True
    assert (
        loaded.reviews["17:abc123"].projection_retry_warning
        == "Review projection warning: projection boom"
    )


def test_update_projection_retry_state_persists_repair_outcome(tmp_path) -> None:
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
        artifact=build_artifact(),
        note_id=55,
        note_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
        projection_retry_pending=True,
        projection_retry_warning="Review projection warning: projection boom",
        dry_run=False,
    )

    service.update_projection_retry_state(
        change_request_number=17,
        head_sha="abc123",
        last_run_id="run-2",
        pending=False,
        warning=None,
    )

    loaded = store.load().reviews["17:abc123"]
    assert loaded.projection_retry_pending is False
    assert loaded.projection_retry_warning is None
    assert loaded.last_run_id == "run-2"


def test_mark_reviewed_mirrors_publish_artifact_metadata_into_local_state(tmp_path) -> None:
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
        artifact=PublishableReviewArtifact(
            classification="findings_present",
            summary="One medium-risk finding.",
            findings=[
                PublishableReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    line_start=12,
                    line_end=13,
                    stable_identity="src/service.py::coverage_gap::service-run::changed-branch",
                    legacy_identity="src/service.py::coverage-miss-test",
                    symbol="Service.run",
                    issue_kind="coverage_gap",
                    region_hint="changed-branch",
                    title="Missing test coverage",
                    evidence="The diff changes a branch without test updates.",
                    explanation="The branch behavior changes without regression coverage.",
                    suggested_follow_up="Add a regression test.",
                    inline_comment=PriorReviewInlineComment(
                        comment_id="789",
                        comment_url="https://gitlab.example.com/comment/789",
                        status="published",
                        anchor_file_path="src/service.py",
                        anchor_line_start=12,
                        anchor_line_end=13,
                    ),
                )
            ],
        ),
        note_id=55,
        note_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
        dry_run=False,
    )

    loaded = store.load()
    finding = loaded.reviews["17:abc123"].findings[0]
    assert loaded.reviews["17:abc123"].summary == "One medium-risk finding."
    assert finding.identity == "src/service.py::coverage_gap::service-run::changed-branch"
    assert finding.line_start == 12
    assert finding.line_end == 13
    assert finding.inline_comment is not None
    assert finding.inline_comment.comment_id == "789"
    assert finding.inline_comment.anchor_line_start == 12
    assert finding.inline_comment.anchor_line_end == 13


def test_mark_reviewed_preserves_continuity_metadata_contract_end_to_end(tmp_path) -> None:
    store = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    )
    service = ReviewStateService(state_store=store, state=build_state())
    record = service.start_run("run-1")

    reconciled_decision = build_reconciled_review_decision(
        PrecisionReviewDecision(
            review_classification="findings_present",
            decision_summary="One medium-risk finding.",
            decision_rationale="The finding is grounded in the reviewed diff.",
            confidence_level=0.84,
            accepted_findings=[
                PrecisionAcceptedFinding(
                    source_candidate_ids=["candidate-1"],
                    severity="medium",
                    file_path="src/service.py",
                    line_start=12,
                    line_end=13,
                    symbol="Service.run",
                    issue_kind="coverage_gap",
                    region_hint="changed-branch",
                    title="Missing regression coverage",
                    summary="Missing regression coverage",
                    evidence=["The diff changes a branch without matching test updates."],
                    why_it_matters="The branch behavior changes without regression coverage.",
                    recommended_follow_up="Add a regression test.",
                )
            ],
            dropped_candidates=[],
        ),
        prior_review_context_used=False,
        same_sha_review=False,
        repair_allowed=True,
        reconciled_at=datetime(2026, 6, 9, 10, 0, 0, tzinfo=UTC),
        pipeline_version="review-staged-v1",
    )
    reconciled_decision.accepted_findings[0].inline_comment = PriorReviewInlineComment(
        comment_id="789",
        comment_url="https://gitlab.example.com/comment/789",
        status="published",
        anchor_file_path="src/service.py",
        anchor_line_start=12,
        anchor_line_end=13,
    )
    artifact = PublishableReviewArtifact.from_reconciled_decision(
        reconciled_decision,
        follow_up_lines=["Follow-up review after the earlier bot pass on `abc123`."],
    )

    service.mark_reviewed(
        record=record,
        merge_request=build_merge_request(),
        artifact=artifact,
        note_id=55,
        note_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
        dry_run=False,
    )

    persisted = store.load().reviews["17:abc123"].findings[0]
    publish_finding = artifact.findings[0]
    reconciled_finding = reconciled_decision.accepted_findings[0]

    assert publish_finding.stable_identity == reconciled_finding.stable_identity
    assert publish_finding.legacy_identity == reconciled_finding.legacy_identity
    assert persisted.identity == reconciled_finding.stable_identity
    assert persisted.legacy_identity == reconciled_finding.legacy_identity
    assert persisted.file_path == reconciled_finding.file_path
    assert persisted.line_start == reconciled_finding.line_start
    assert persisted.line_end == reconciled_finding.line_end
    assert persisted.title == reconciled_finding.title
    assert persisted.symbol == reconciled_finding.symbol
    assert persisted.issue_kind == reconciled_finding.issue_kind
    assert persisted.region_hint == reconciled_finding.region_hint
    assert persisted.summary == "src/service.py: Missing regression coverage"
    assert persisted.inline_comment is not None
    assert persisted.inline_comment.comment_id == "789"
    assert persisted.inline_comment.comment_url == "https://gitlab.example.com/comment/789"
    assert persisted.inline_comment.anchor_file_path == reconciled_finding.file_path
    assert persisted.inline_comment.anchor_line_start == reconciled_finding.line_start
    assert persisted.inline_comment.anchor_line_end == reconciled_finding.line_end


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
        artifact=PublishableReviewArtifact(
            classification="no_findings",
            summary="No findings.",
            findings=[],
        ),
        note_id=None,
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
        artifact=PublishableReviewArtifact(
            classification="manual_review_only",
            summary="The available context was insufficient.",
            findings=[],
        ),
        note_id=None,
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
            artifact=build_artifact(),
            note_id=None,
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
            artifact=build_artifact(),
            note_id=None,
            note_url=f"https://gitlab.example.com/note/{run_id}",
            dry_run=False,
        )

    prior_review_context = service.load_prior_review_context(
        change_request_number=17,
        current_head_sha="sha-3",
    )

    assert isinstance(prior_review_context, PriorReviewContext)
    assert prior_review_context.change_request_number == 17
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
    assert prior_review_context.passes[0].findings[0].file_path == "src/service.py"
    assert prior_review_context.passes[0].findings[0].title == "Ordering regression"
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
        artifact=PublishableReviewArtifact(
            classification="findings_present",
            summary="Two findings.",
            findings=[
                PublishableReviewFinding(
                    severity="high",
                    file_path="bnl_app/functions/vehicle_functions.py",
                    stable_identity=(
                        "bnl_app/functions/vehicle_functions.py::"
                        "unconditional_exception::get_vehicle_details_short::function-entry"
                    ),
                    legacy_identity=(
                        "bnl_app/functions/vehicle_functions.py::"
                        "detail-except-fail-lookup-unconditional-vehicle"
                    ),
                    symbol="get_vehicle_details_short",
                    issue_kind="unconditional_exception",
                    region_hint="function-entry",
                    title="Unconditional exception breaks vehicle detail retrieval",
                    evidence="The diff inserts `raise ValueError` at the top of the helper.",
                    explanation="The helper now throws before any normal lookup logic runs.",
                    suggested_follow_up="Remove the unconditional exception.",
                ),
                PublishableReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    stable_identity="src/service.py::coverage_gap::service-run",
                    legacy_identity="src/service.py::coverage-miss-test",
                    symbol="Service.run",
                    issue_kind="coverage_gap",
                    title="Missing test coverage",
                    evidence="The diff changes a branch without any test updates.",
                    explanation="The change alters branch behavior without regression coverage.",
                    suggested_follow_up="Add a regression test for the changed branch.",
                ),
            ],
        ),
        note_id=None,
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
    assert loaded.reviews["17:abc123"].findings[0].file_path == (
        "bnl_app/functions/vehicle_functions.py"
    )
    assert loaded.reviews["17:abc123"].findings[0].title == (
        "Unconditional exception breaks vehicle detail retrieval"
    )
    assert loaded.reviews["17:abc123"].findings[1].identity == (
        "src/service.py::coverage_gap::service-run"
    )
    assert loaded.reviews["17:abc123"].findings[1].summary == (
        "src/service.py: Missing test coverage"
    )
    assert loaded.reviews["17:abc123"].findings[1].file_path == "src/service.py"
    assert loaded.reviews["17:abc123"].findings[1].title == "Missing test coverage"
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
    state.reviews["17:sha-2"] = ChangeRequestReviewState(
        change_request_number=17,
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
                file_path="src/service.py",
                title="Ordering regression",
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
        change_request_number=17,
        current_head_sha="sha-3",
    )

    assert isinstance(prior_review_context, PriorReviewContext)
    assert prior_review_context.passes[0].findings[0].identity == "src/service.py::order-regress"
    assert (
        prior_review_context.passes[0].findings[0].summary == "src/service.py: Ordering regression"
    )
    assert prior_review_context.passes[0].findings[0].file_path == "src/service.py"
    assert prior_review_context.passes[0].findings[0].title == "Ordering regression"
    assert prior_review_context.passes[0].findings[0].symbol == "Service.run"
    assert prior_review_context.passes[0].findings[0].issue_kind == "ordering_regression"
    assert prior_review_context.passes[0].findings[0].region_hint == "return-order"
    assert prior_review_context.passes[0].findings[1].identity is None
    assert prior_review_context.passes[0].findings[1].summary == "Legacy helper concern"
