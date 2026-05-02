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
    PrecisionAcceptedFinding,
    PrecisionReviewDecision,
    PriorReviewContext,
    PriorReviewPass,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from zeroone_ops.providers.llm_client import LLMClientError
from zeroone_ops.services.review.review_candidate_generation_service import (
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
                    line_start=1,
                    line_end=1,
                    title="Missing regression coverage",
                    evidence="The diff changes `value = 1` to `value = 2` without test updates.",
                    explanation="The branch behavior changes without regression coverage.",
                    suggested_follow_up="Add a regression test.",
                ),
                CandidateReviewFinding(
                    candidate_id="candidate-2",
                    severity="medium",
                    file_path="src/service.py",
                    title="Duplicate framing of the same issue",
                    evidence="The diff changes `value = 1` to `value = 2` without test updates.",
                    explanation="This is the same behavior change described more loosely.",
                    suggested_follow_up="Add a regression test.",
                ),
            ]
        ),
        raw_review_result=ReviewResult(
            classification="findings_present",
            summary="Two candidate findings.",
            review_confidence=0.84,
            review_confidence_reason="The candidate findings are grounded in the reviewed diff.",
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
        accepted_candidate_ids=("candidate-1", "candidate-2"),
        dropped_candidates=(),
        message="Candidate review generated 2 candidates and accepted 2 findings.",
    )


class FakePrecisionLLMClient:
    def __init__(self, decision: PrecisionReviewDecision) -> None:
        self.decision = decision

    def review_precision_reconciliation(
        self,
        context: MergeRequestReviewContext,
        *,
        candidates: list[CandidateReviewFinding],
        overlap_packet,
        candidate_stage_summary: str,
        candidate_stage_classification: str,
        candidate_stage_rationale: str,
        max_findings: int,
    ) -> PrecisionReviewDecision:
        del (
            context,
            candidates,
            overlap_packet,
            candidate_stage_summary,
            candidate_stage_classification,
            candidate_stage_rationale,
            max_findings,
        )
        return self.decision


class FakePrecisionErrorClient:
    def review_precision_reconciliation(
        self,
        context: MergeRequestReviewContext,
        *,
        candidates: list[CandidateReviewFinding],
        overlap_packet,
        candidate_stage_summary: str,
        candidate_stage_classification: str,
        candidate_stage_rationale: str,
        max_findings: int,
    ) -> PrecisionReviewDecision:
        del (
            context,
            candidates,
            overlap_packet,
            candidate_stage_summary,
            candidate_stage_classification,
            candidate_stage_rationale,
            max_findings,
        )
        raise LLMClientError("bad precision output")


def test_reconcile_uses_precision_output_as_final_review_meaning(monkeypatch) -> None:
    service = ReviewReconciliationService(
        build_config(),
        llm_client_builder=lambda: FakePrecisionLLMClient(
            PrecisionReviewDecision(
                review_classification="findings_present",
                decision_summary="One medium-risk finding remains after precision review.",
                decision_rationale="Candidate 2 duplicates candidate 1 and was dropped.",
                confidence_level=0.79,
                accepted_findings=[
                    PrecisionAcceptedFinding(
                        source_candidate_ids=["candidate-1"],
                        severity="medium",
                        file_path="src/service.py",
                        line_start=1,
                        line_end=1,
                        title="Missing regression coverage",
                        summary="A behavior change survives without matching test updates.",
                        evidence=[
                            "The diff changes `value = 1` to `value = 2` without test updates."
                        ],
                        why_it_matters="The branch behavior changes without regression coverage.",
                        recommended_follow_up="Add a regression test.",
                    )
                ],
                dropped_candidates=[
                    {
                        "candidate_id": "candidate-2",
                        "drop_reason": "duplicate",
                        "notes": "Overlaps candidate-1 on the same behavior change.",
                    }
                ],
            )
        ),
    )
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
    assert result.review_result.summary == "One medium-risk finding remains after precision review."
    assert result.review_result.findings[0].line_start == 1
    assert result.reconciled_decision.accepted_findings[0].source_candidate_ids == ["candidate-1"]
    assert result.reconciled_decision.dropped_candidates[0].candidate_id == "candidate-2"
    assert result.reconciled_decision.reconciled_at == datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def test_reconcile_attaches_continuity_status_from_overlap_result() -> None:
    service = ReviewReconciliationService(
        build_config(),
        llm_client_builder=lambda: FakePrecisionLLMClient(
            PrecisionReviewDecision(
                review_classification="findings_present",
                decision_summary="One finding persists.",
                decision_rationale="The candidate remains grounded at the current SHA.",
                accepted_findings=[
                    PrecisionAcceptedFinding(
                        source_candidate_ids=["candidate-1"],
                        severity="medium",
                        file_path="src/service.py",
                        title="Missing regression coverage",
                        summary="Coverage is still missing for the changed behavior.",
                        evidence=[
                            "The diff changes `value = 1` to `value = 2` without test updates."
                        ],
                        why_it_matters="The branch behavior changes without regression coverage.",
                        recommended_follow_up="Add a regression test.",
                    )
                ],
                dropped_candidates=[
                    {
                        "candidate_id": "candidate-2",
                        "drop_reason": "duplicate",
                        "notes": "Overlaps candidate-1 on the same behavior change.",
                    }
                ],
            )
        ),
    )
    service._reconcile_overlap = lambda *, context, review_result: OverlapReconciliationResult(
        prior_reviewed_head_sha="prior-sha",
        resolutions=[
            OverlapResolution(
                outcome="still_unresolved",
                current_finding_index=0,
                prior_finding_index=0,
                related_prior_finding_indices=[0],
            )
        ],
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


def test_reconcile_returns_failure_when_precision_backend_errors() -> None:
    service = ReviewReconciliationService(
        build_config(),
        llm_client_builder=lambda: FakePrecisionErrorClient(),
    )

    result = service.reconcile(
        context=build_context(),
        candidate_stage_result=build_candidate_stage_result(),
    )

    assert result.review_result is None
    assert result.reconciled_decision is None
    assert result.message == "Review precision reconciliation failed: bad precision output"


def test_reconcile_downgrades_to_manual_review_when_precision_output_is_invalid() -> None:
    service = ReviewReconciliationService(
        build_config(),
        llm_client_builder=lambda: FakePrecisionLLMClient(
            PrecisionReviewDecision(
                review_classification="no_findings",
                decision_summary="No actionable findings.",
                decision_rationale="Candidate coverage is ambiguous.",
                accepted_findings=[
                    PrecisionAcceptedFinding(
                        source_candidate_ids=["candidate-1"],
                        severity="medium",
                        file_path="src/service.py",
                        title="Should not survive",
                        summary="This should force fallback.",
                        evidence=["The diff changes `value = 1` to `value = 2`."],
                        why_it_matters="The precision output is inconsistent.",
                    )
                ],
                dropped_candidates=[],
            )
        ),
    )

    result = service.reconcile(
        context=build_context(),
        candidate_stage_result=build_candidate_stage_result(),
    )

    assert result.review_result is not None
    assert result.review_result.classification == "manual_review_only"
    assert result.reconciled_decision is not None
    assert result.reconciled_decision.decision_rationale == (
        "Precision pass returned accepted findings with a non-findings classification."
    )


def test_reconcile_downgrades_when_precision_reuses_candidate_across_findings() -> None:
    service = ReviewReconciliationService(
        build_config(),
        llm_client_builder=lambda: FakePrecisionLLMClient(
            PrecisionReviewDecision(
                review_classification="findings_present",
                decision_summary="Two findings remain.",
                decision_rationale="Both findings appear grounded.",
                accepted_findings=[
                    PrecisionAcceptedFinding(
                        source_candidate_ids=["candidate-1"],
                        severity="medium",
                        file_path="src/service.py",
                        title="First framing",
                        summary="First framing.",
                        evidence=["The diff changes `value = 1` to `value = 2`."],
                        why_it_matters="Reason one.",
                    ),
                    PrecisionAcceptedFinding(
                        source_candidate_ids=["candidate-1"],
                        severity="medium",
                        file_path="src/service.py",
                        title="Second framing",
                        summary="Second framing.",
                        evidence=["The diff changes `value = 1` to `value = 2`."],
                        why_it_matters="Reason two.",
                    ),
                ],
                dropped_candidates=[
                    {
                        "candidate_id": "candidate-2",
                        "drop_reason": "duplicate",
                        "notes": "Overlaps candidate-1.",
                    }
                ],
            )
        ),
    )

    result = service.reconcile(
        context=build_context(),
        candidate_stage_result=build_candidate_stage_result(),
    )

    assert result.review_result is not None
    assert result.review_result.classification == "manual_review_only"
    assert result.reconciled_decision is not None
    assert result.reconciled_decision.decision_rationale == (
        "Precision pass assigned the same grounded candidate to multiple accepted findings."
    )
