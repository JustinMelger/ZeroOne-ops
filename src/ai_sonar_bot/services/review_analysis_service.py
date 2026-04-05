"""Review analysis service."""

from __future__ import annotations

from dataclasses import dataclass

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.review import MergeRequestReviewContext, ReviewResult
from ai_sonar_bot.providers.llm_client import FixtureLLMClient, LLMClientError, OpenAILLMClient
from ai_sonar_bot.settings import SettingsError, load_openai_connection_config


@dataclass(frozen=True)
class ReviewAnalysisResult:
    """Capture the outcome of merge-request review analysis."""

    review_result: ReviewResult | None
    message: str


class ReviewAnalysisService:
    """Request structured merge-request review findings from the active LLM."""

    def __init__(self, config: AppConfig) -> None:
        """Initialize the review analysis service."""
        self.config = config

    def analyze(self, context: MergeRequestReviewContext) -> ReviewAnalysisResult:
        """Analyze one merge request context."""
        llm_client = self._build_llm_client()
        if llm_client is None:
            return ReviewAnalysisResult(
                review_result=None,
                message="LLM backend not configured for merge request review.",
            )

        try:
            review_result = llm_client.review_merge_request(context)
        except LLMClientError as error:
            return ReviewAnalysisResult(
                review_result=None,
                message=f"Structured merge request review failed: {error}",
            )

        return ReviewAnalysisResult(
            review_result=review_result,
            message=(
                f"Review classification: {review_result.classification}. "
                f"Summary: {review_result.summary}"
            ),
        )

    def _build_llm_client(self) -> FixtureLLMClient | OpenAILLMClient | None:
        """Build the configured review LLM client."""
        try:
            return OpenAILLMClient(load_openai_connection_config(), solution_output_path=None)
        except SettingsError:
            return None
