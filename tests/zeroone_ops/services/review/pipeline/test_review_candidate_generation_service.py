from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
    ReviewConfig,
)
from zeroone_ops.models.review import (
    ChangeRequestReviewContext,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from zeroone_ops.providers.llm_client import LLMClientError
from zeroone_ops.services.review.pipeline.review_candidate_generation_service import (
    ReviewCandidateGenerationService,
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


def build_context() -> ChangeRequestReviewContext:
    return ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
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


class FakeReviewLLMClient:
    def __init__(self, review_result: ReviewResult) -> None:
        self.review_result = review_result

    def review_merge_request(self, context: ChangeRequestReviewContext) -> ReviewResult:
        del context
        return self.review_result


class FakeReviewErrorClient:
    def review_merge_request(self, context: ChangeRequestReviewContext) -> ReviewResult:
        del context
        raise LLMClientError("bad output")


def test_analyze_returns_explicit_candidate_stage_result(monkeypatch) -> None:
    service = ReviewCandidateGenerationService(build_config())
    monkeypatch.setattr(
        service,
        "_build_llm_client",
        lambda: FakeReviewLLMClient(
            ReviewResult(
                classification="findings_present",
                summary="One finding.",
                findings=[
                    ReviewFinding(
                        severity="medium",
                        file_path="src/service.py",
                        title="Missing guard",
                        evidence="The diff changes `value = 1` to `value = 2` in src/service.py.",
                        explanation="The change alters behavior without test updates.",
                        suggested_follow_up="Add a regression test.",
                    )
                ],
            )
        ),
    )

    result = service.analyze(build_context())

    assert result.candidate_result is not None
    assert result.raw_review_result is not None
    assert len(result.candidate_result.findings) == 1
    assert result.candidate_result.findings[0].candidate_id == "candidate-1"
    assert result.candidate_ids == ("candidate-1",)
    assert result.pre_precision_dropped_candidates == ()
    assert result.raw_review_result.classification == "findings_present"


def test_analyze_forwards_candidates_without_pre_precision_filtering(monkeypatch) -> None:
    service = ReviewCandidateGenerationService(build_config())
    monkeypatch.setattr(
        service,
        "_build_llm_client",
        lambda: FakeReviewLLMClient(
            ReviewResult(
                classification="findings_present",
                summary="One finding.",
                review_confidence=0.41,
                review_confidence_reason="The issue depends on context not visible in the diff.",
                findings=[
                    ReviewFinding(
                        severity="medium",
                        file_path="src/other.py",
                        title="Missing guard",
                        evidence="The diff in src/other.py removes the only null check.",
                        explanation="The change can dereference a nullable value.",
                        suggested_follow_up="Restore the guard.",
                    )
                ],
            )
        ),
    )

    result = service.analyze(build_context())

    assert result.candidate_result is not None
    assert result.raw_review_result is not None
    assert result.raw_review_result.classification == "findings_present"
    assert result.candidate_ids == ("candidate-1",)
    assert result.pre_precision_dropped_candidates == ()


def test_analyze_reports_structured_review_failure(monkeypatch) -> None:
    service = ReviewCandidateGenerationService(build_config())
    monkeypatch.setattr(service, "_build_llm_client", lambda: FakeReviewErrorClient())

    result = service.analyze(build_context())

    assert result.candidate_result is None
    assert result.raw_review_result is None
    assert result.message == "Structured change-request review failed: bad output"
