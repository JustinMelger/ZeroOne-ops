from ai_sonar_bot.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    ReviewConfig,
)
from ai_sonar_bot.models.review import (
    MergeRequestReviewContext,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from ai_sonar_bot.services.review_analysis_service import ReviewAnalysisService


def build_config() -> AppConfig:
    return AppConfig(
        base_branch="main",
        supported_severities=["LOW"],
        supported_issue_types=["CODE_SMELL"],
        validation_commands=[],
        analysis=AnalysisConfig(),
        approval=ApprovalConfig(),
        review=ReviewConfig(),
        gitlab=GitLabConfig(target_branch="main"),
    )


def build_context() -> MergeRequestReviewContext:
    return MergeRequestReviewContext(
        mr_iid=17,
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

    def review_merge_request(self, context: MergeRequestReviewContext) -> ReviewResult:
        del context
        return self.review_result


class FakeReviewErrorClient:
    def review_merge_request(self, context: MergeRequestReviewContext) -> ReviewResult:
        from ai_sonar_bot.providers.llm_client import LLMClientError

        del context
        raise LLMClientError("bad output")


def test_analyze_returns_structured_review_result(monkeypatch) -> None:
    service = ReviewAnalysisService(build_config())
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

    assert result.review_result is not None
    assert result.review_result.classification == "findings_present"
    assert "Review classification: findings_present" in result.message


def test_analyze_reports_missing_llm_backend(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    result = ReviewAnalysisService(build_config()).analyze(build_context())

    assert result.review_result is None
    assert result.message == "LLM backend not configured for merge request review."


def test_analyze_reports_structured_review_failure(monkeypatch) -> None:
    service = ReviewAnalysisService(build_config())
    monkeypatch.setattr(service, "_build_llm_client", lambda: FakeReviewErrorClient())

    result = service.analyze(build_context())

    assert result.review_result is None
    assert result.message == "Structured merge request review failed: bad output"


def test_analyze_drops_findings_for_unreviewed_files(monkeypatch) -> None:
    service = ReviewAnalysisService(build_config())
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

    assert result.review_result is not None
    assert result.review_result.classification == "no_findings"
    assert result.review_result.summary == "No actionable findings after review validation."


def test_analyze_drops_findings_with_generic_evidence(monkeypatch) -> None:
    service = ReviewAnalysisService(build_config())
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
                        evidence="The change may be risky.",
                        explanation="The change can dereference a nullable value.",
                        suggested_follow_up="Restore the guard.",
                    )
                ],
            )
        ),
    )

    result = service.analyze(build_context())

    assert result.review_result is not None
    assert result.review_result.classification == "no_findings"
    assert result.review_result.summary == "No actionable findings after review validation."


def test_analyze_drops_speculative_findings_even_when_file_matches(monkeypatch) -> None:
    service = ReviewAnalysisService(build_config())
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
                        title="Potential issue",
                        evidence="The diff changes `value = 1` to `value = 2` in src/service.py.",
                        explanation="This change may be risky.",
                        suggested_follow_up="Review this area manually.",
                    )
                ],
            )
        ),
    )

    result = service.analyze(build_context())

    assert result.review_result is not None
    assert result.review_result.classification == "no_findings"
    assert result.review_result.summary == "No actionable findings after review validation."


def test_analyze_keeps_findings_with_grounded_evidence(monkeypatch) -> None:
    service = ReviewAnalysisService(build_config())
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
                        explanation=(
                            "The diff changes behavior in src/service.py without any "
                            "matching regression test update."
                        ),
                        suggested_follow_up="Add a regression test.",
                    )
                ],
            )
        ),
    )

    result = service.analyze(build_context())

    assert result.review_result is not None
    assert result.review_result.classification == "findings_present"
    assert len(result.review_result.findings) == 1
