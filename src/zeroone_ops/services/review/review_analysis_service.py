"""Legacy review analysis adapter."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    MergeRequestReviewContext,
    ReviewResult,
)
from zeroone_ops.providers.llm_client import FixtureLLMClient, OpenAILLMClient
from zeroone_ops.services.review.review_candidate_generation_service import (
    ReviewCandidateGenerationService,
)
from zeroone_ops.services.review.review_reconciliation_service import (
    ReviewReconciliationService,
)
from zeroone_ops.settings import SettingsError, load_openai_connection_config


@dataclass(frozen=True)
class ReviewAnalysisResult:
    """Capture the outcome of merge-request review analysis."""

    review_result: ReviewResult | None
    message: str


class ReviewAnalysisService:
    """Compatibility adapter over the explicit candidate review stage."""

    def __init__(self, config: AppConfig) -> None:
        """Initialize the review analysis service."""
        self.config = config

    def analyze(self, context: MergeRequestReviewContext) -> ReviewAnalysisResult:
        """Analyze one merge request context through candidate and reconciliation stages."""
        candidate_stage_result = ReviewCandidateGenerationService(
            self.config,
            llm_client_builder=self._build_llm_client,
        ).analyze(context)
        reconciliation_result = ReviewReconciliationService(self.config).reconcile(
            context=context,
            candidate_stage_result=candidate_stage_result,
        )
        review_result = reconciliation_result.review_result
        if review_result is None:
            return ReviewAnalysisResult(
                review_result=None,
                message=reconciliation_result.message,
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
