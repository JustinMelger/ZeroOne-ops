from ai_sonar_bot.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
    ReviewConfig,
)
from ai_sonar_bot.models.review import (
    OverlapCandidate,
    OverlapPacket,
    OverlapReconciliationResult,
    OverlapResolution,
    PriorReviewFinding,
    ReviewFinding,
)
from ai_sonar_bot.services.review.review_overlap_analysis_service import (
    ReviewOverlapAnalysisService,
)


def build_config() -> AppConfig:
    return AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            supported_severities=["LOW"],
            analysis=AnalysisConfig(),
        ),
        review=ReviewConfig(),
        gitlab=GitLabConfig(target_branch="main"),
    )


def build_packet() -> OverlapPacket:
    return OverlapPacket(
        merge_request_iid=17,
        current_head_sha="def456",
        prior_head_sha="abc123",
        current_findings=[
            ReviewFinding(
                severity="medium",
                file_path="src/service.py",
                title="Missing test coverage",
                evidence="`value = 2` changed without test updates.",
                explanation="The branch behavior changed without regression coverage.",
                suggested_follow_up="Add a regression test.",
            )
        ],
        prior_findings=[
            PriorReviewFinding(
                identity="src/service.py::missing-test-coverage",
                summary="src/service.py: Missing test coverage",
            )
        ],
        candidates=[
            OverlapCandidate(
                current_finding_index=0,
                prior_finding_index=0,
                reasons=["canonical_identity"],
            )
        ],
    )


class FakeReviewOverlapLLMClient:
    def __init__(self, result: OverlapReconciliationResult) -> None:
        self.result = result

    def review_overlap_reconciliation(
        self,
        packet: OverlapPacket,
    ) -> OverlapReconciliationResult:
        del packet
        return self.result


class FakeReviewOverlapErrorClient:
    def review_overlap_reconciliation(
        self,
        packet: OverlapPacket,
    ) -> OverlapReconciliationResult:
        from ai_sonar_bot.providers.llm_client import LLMClientError

        del packet
        raise LLMClientError("bad overlap output")


def test_analyze_returns_structured_overlap_result(monkeypatch) -> None:
    service = ReviewOverlapAnalysisService(build_config())
    monkeypatch.setattr(
        service,
        "_build_llm_client",
        lambda: FakeReviewOverlapLLMClient(
            OverlapReconciliationResult(
                prior_reviewed_head_sha="abc123",
                resolutions=[
                    OverlapResolution(
                        outcome="still_unresolved",
                        current_finding_index=0,
                        prior_finding_index=0,
                        related_prior_finding_indices=[0],
                    )
                ],
            )
        ),
    )

    result = service.analyze(build_packet())

    assert result.overlap_result is not None
    assert result.status == "ok"
    assert result.overlap_result.prior_reviewed_head_sha == "abc123"
    assert "Review overlap reconciled against prior SHA: abc123." == result.message


def test_analyze_reports_missing_llm_backend(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    result = ReviewOverlapAnalysisService(build_config()).analyze(build_packet())

    assert result.overlap_result is None
    assert result.status == "no_backend"
    assert result.message == "LLM backend not configured for review overlap reconciliation."


def test_analyze_reports_structured_overlap_failure(monkeypatch) -> None:
    service = ReviewOverlapAnalysisService(build_config())
    monkeypatch.setattr(service, "_build_llm_client", lambda: FakeReviewOverlapErrorClient())

    result = service.analyze(build_packet())

    assert result.overlap_result is None
    assert result.status == "llm_error"
    assert result.message == "Structured review overlap reconciliation failed: bad overlap output"


def test_analyze_rejects_overlap_result_with_wrong_prior_sha(monkeypatch) -> None:
    service = ReviewOverlapAnalysisService(build_config())
    monkeypatch.setattr(
        service,
        "_build_llm_client",
        lambda: FakeReviewOverlapLLMClient(
            OverlapReconciliationResult(
                prior_reviewed_head_sha="wrong-sha",
                resolutions=[],
            )
        ),
    )

    result = service.analyze(build_packet())

    assert result.overlap_result is None
    assert result.status == "invalid_result"
    assert result.message == (
        "Structured review overlap reconciliation returned an invalid result: "
        "prior reviewed SHA does not match the overlap packet"
    )


def test_analyze_rejects_overlap_result_outside_candidate_boundary(monkeypatch) -> None:
    service = ReviewOverlapAnalysisService(build_config())
    monkeypatch.setattr(
        service,
        "_build_llm_client",
        lambda: FakeReviewOverlapLLMClient(
            OverlapReconciliationResult(
                prior_reviewed_head_sha="abc123",
                resolutions=[
                    OverlapResolution(
                        outcome="still_unresolved",
                        current_finding_index=0,
                        prior_finding_index=0,
                        related_prior_finding_indices=[0],
                    ),
                    OverlapResolution(
                        outcome="still_unresolved",
                        current_finding_index=0,
                        prior_finding_index=1,
                    ),
                ],
            )
        ),
    )

    result = service.analyze(build_packet())

    assert result.overlap_result is None
    assert result.status == "invalid_result"
    assert result.message == (
        "Structured review overlap reconciliation returned an invalid result: "
        "prior finding index is out of range"
    )


def test_analyze_rejects_overlap_result_reusing_one_current_finding(monkeypatch) -> None:
    service = ReviewOverlapAnalysisService(build_config())
    monkeypatch.setattr(
        service,
        "_build_llm_client",
        lambda: FakeReviewOverlapLLMClient(
            OverlapReconciliationResult(
                prior_reviewed_head_sha="abc123",
                resolutions=[
                    OverlapResolution(
                        outcome="still_unresolved",
                        current_finding_index=0,
                        prior_finding_index=0,
                        related_prior_finding_indices=[0],
                    ),
                    OverlapResolution(
                        outcome="new_in_this_pass",
                        current_finding_index=0,
                    ),
                ],
            )
        ),
    )

    result = service.analyze(build_packet())

    assert result.overlap_result is None
    assert result.status == "invalid_result"
    assert result.message == (
        "Structured review overlap reconciliation returned an invalid result: "
        "current finding is referenced by multiple overlap resolutions"
    )


def test_analyze_rejects_overlap_result_reusing_one_prior_finding(monkeypatch) -> None:
    service = ReviewOverlapAnalysisService(build_config())
    monkeypatch.setattr(
        service,
        "_build_llm_client",
        lambda: FakeReviewOverlapLLMClient(
            OverlapReconciliationResult(
                prior_reviewed_head_sha="abc123",
                resolutions=[
                    OverlapResolution(
                        outcome="still_unresolved",
                        current_finding_index=0,
                        prior_finding_index=0,
                        related_prior_finding_indices=[0],
                    ),
                    OverlapResolution(
                        outcome="no_longer_present",
                        prior_finding_index=0,
                        related_prior_finding_indices=[0],
                    ),
                ],
            )
        ),
    )

    result = service.analyze(build_packet())

    assert result.overlap_result is None
    assert result.status == "invalid_result"
    assert result.message == (
        "Structured review overlap reconciliation returned an invalid result: "
        "prior finding is referenced by multiple overlap resolutions"
    )
