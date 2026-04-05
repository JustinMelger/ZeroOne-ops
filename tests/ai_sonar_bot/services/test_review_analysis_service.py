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
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
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
                findings=[],
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
