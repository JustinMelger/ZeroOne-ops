from datetime import UTC, datetime

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
    ReviewConfig,
)
from zeroone_ops.models.review import (
    CandidateReviewFinding,
    CandidateReviewResult,
    MergeRequestReviewContext,
    OverlapReconciliationResult,
    OverlapResolution,
    PriorReviewContext,
    PriorReviewPass,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from zeroone_ops.services.review.review_candidate_service import (
    ReviewCandidateStageResult,
)
from zeroone_ops.services.review.review_reconciliation_service import (
    ReviewReconciliationService,
)


def build_config() -> AppConfig:
    return AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            bootstrap_severities=["LOW"],
            analysis=AnalysisConfig(),
        ),
        review=ReviewConfig(),
        gitlab=GitLabConfig(target_branch="main"),
    )


def build_context(with_prior: bool = False) -> MergeRequestReviewContext:
    prior_review_context = None
    if with_prior:
        prior_review_context = PriorReviewContext(
            merge_request_iid=17,
            passes=[
                PriorReviewPass(
                    reviewed_head_sha="prior-sha",
                    classification="findings_present",
                    findings_count=1,
                    summary="Earlier finding.",
                    findings=[],
                )
            ],
        )
    return MergeRequestReviewContext(
        mr_iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="current-sha",
        prior_review_context=prior_review_context,
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@\n-value = 1\n+value = 2\n",
                start_line=1,
                end_line=1,
                content="   1: value = 2",
                full_file_included=True,
                truncated=False,
            )
        ],
    )


def build_candidate_stage_result() -> ReviewCandidateStageResult:
    return ReviewCandidateStageResult(
        candidate_result=CandidateReviewResult(
            findings=[
                CandidateReviewFinding(
                    candidate_id="candidate-1",
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing regression coverage",
                    evidence="The diff changes `value = 1` to `value = 2` without test updates.",
                    explanation="The branch behavior changes without regression coverage.",
                    suggested_follow_up="Add a regression test.",
                ),
                CandidateReviewFinding(
                    candidate_id="candidate-2",
                    severity="medium",
                    file_path="src/other.py",
                    title="Dropped off-diff concern",
                    evidence="The diff in src/other.py removes the only null check.",
                    explanation="The change can dereference a nullable value.",
                    suggested_follow_up="Restore the guard.",
                ),
            ]
        ),
        raw_review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            review_confidence=0.84,
            review_confidence_reason="The finding is grounded in the reviewed diff.",
            findings=[
                ReviewFinding(
                    severity="medium",
                    file_path="src/service.py",
                    title="Missing regression coverage",
                    evidence="The diff changes `value = 1` to `value = 2` without test updates.",
                    explanation="The branch behavior changes without regression coverage.",
                    suggested_follow_up="Add a regression test.",
                )
            ],
        ),
        accepted_candidate_ids=("candidate-1",),
        dropped_candidates=(),
        message="Candidate review generated 2 candidates and accepted 1 findings.",
    )


def test_reconcile_builds_final_decision_and_attaches_candidate_provenance(monkeypatch) -> None:
    service = ReviewReconciliationService(build_config())
    monkeypatch.setattr(
        "zeroone_ops.services.review.review_reconciliation_service.now_utc",
        lambda: datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(
        service,
        "_reconcile_overlap",
        lambda *, context, review_result: None,
    )

    result = service.reconcile(
        context=build_context(),
        candidate_stage_result=build_candidate_stage_result(),
    )

    assert result.review_result is not None
    assert result.reconciled_decision is not None
    assert result.review_result.classification == "findings_present"
    assert result.reconciled_decision.review_classification == "findings_present"
    assert result.reconciled_decision.accepted_findings[0].source_candidate_ids == ["candidate-1"]
    assert result.reconciled_decision.reconciled_at == datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def test_reconcile_attaches_continuity_status_from_overlap_result(monkeypatch) -> None:
    service = ReviewReconciliationService(build_config())
    monkeypatch.setattr(
        service,
        "_reconcile_overlap",
        lambda *, context, review_result: OverlapReconciliationResult(
            prior_reviewed_head_sha="prior-sha",
            resolutions=[
                OverlapResolution(
                    outcome="still_unresolved",
                    current_finding_index=0,
                    prior_finding_index=0,
                    related_prior_finding_indices=[0],
                )
            ],
        ),
    )

    result = service.reconcile(
        context=build_context(with_prior=True),
        candidate_stage_result=build_candidate_stage_result(),
    )

    assert result.overlap_result is not None
    assert result.reconciled_decision is not None
    assert result.reconciled_decision.prior_review_context_used is True
    assert result.reconciled_decision.accepted_findings[0].continuity_status == "unresolved"


def test_reconcile_returns_candidate_failure_when_no_authoritative_review_exists() -> None:
    service = ReviewReconciliationService(build_config())

    result = service.reconcile(
        context=build_context(),
        candidate_stage_result=ReviewCandidateStageResult(
            candidate_result=None,
            raw_review_result=None,
            accepted_candidate_ids=(),
            dropped_candidates=(),
            message="LLM backend not configured for merge request review.",
        ),
    )

    assert result.review_result is None
    assert result.reconciled_decision is None
    assert result.overlap_result is None
    assert result.message == "LLM backend not configured for merge request review."
