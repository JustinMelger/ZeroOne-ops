"""Review candidate generation service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    CandidateReviewFinding,
    CandidateReviewResult,
    ChangeRequestReviewContext,
    DroppedCandidate,
    ReviewResult,
)
from zeroone_ops.providers.llm_client import (
    FixtureLLMClient,
    LLMClientError,
    OpenAILLMClient,
)
from zeroone_ops.settings import SettingsError, load_openai_connection_config


@dataclass(frozen=True)
class ReviewCandidateStageResult:
    """Capture the explicit candidate-stage outcome for one review pass."""

    candidate_result: CandidateReviewResult | None
    raw_review_result: ReviewResult | None
    candidate_ids: tuple[str, ...]
    pre_precision_dropped_candidates: tuple[DroppedCandidate, ...]
    message: str


class ReviewCandidateGenerationService:
    """Generate non-authoritative review candidates and ground them safely."""

    def __init__(
        self,
        config: AppConfig,
        llm_client_builder: Callable[[], FixtureLLMClient | OpenAILLMClient | None] | None = None,
    ) -> None:
        """Initialize the candidate review service."""
        self.config = config
        self._llm_client_builder = llm_client_builder

    def analyze(self, context: ChangeRequestReviewContext) -> ReviewCandidateStageResult:
        """Generate candidate findings, then ground them without deciding final truth."""
        llm_client = self._build_llm_client()
        if llm_client is None:
            return ReviewCandidateStageResult(
                candidate_result=None,
                raw_review_result=None,
                candidate_ids=(),
                pre_precision_dropped_candidates=(),
                message="LLM backend not configured for change-request review.",
            )

        try:
            raw_review_result = llm_client.review_merge_request(context)
        except LLMClientError as error:
            return ReviewCandidateStageResult(
                candidate_result=None,
                raw_review_result=None,
                candidate_ids=(),
                pre_precision_dropped_candidates=(),
                message=f"Structured change-request review failed: {error}",
            )

        candidate_result = _candidate_review_result_from_review_result(raw_review_result)
        candidate_ids = tuple(finding.candidate_id for finding in candidate_result.findings)

        return ReviewCandidateStageResult(
            candidate_result=candidate_result,
            raw_review_result=raw_review_result,
            candidate_ids=candidate_ids,
            pre_precision_dropped_candidates=(),
            message=(
                "Candidate review generated "
                f"{len(candidate_result.findings)} candidates and forwarded "
                f"{len(candidate_ids)} findings to precision."
            ),
        )

    def _build_llm_client(self) -> FixtureLLMClient | OpenAILLMClient | None:
        """Build the configured review LLM client."""
        if self._llm_client_builder is not None:
            return self._llm_client_builder()
        try:
            return OpenAILLMClient(load_openai_connection_config(), solution_output_path=None)
        except SettingsError:
            return None


def _candidate_review_result_from_review_result(
    review_result: ReviewResult,
) -> CandidateReviewResult:
    """Adapt the raw LLM review output into an explicit candidate artifact."""
    if review_result.classification != "findings_present":
        return CandidateReviewResult()

    return CandidateReviewResult(
        findings=[
            CandidateReviewFinding(
                candidate_id=f"candidate-{index}",
                severity=finding.severity,
                file_path=finding.file_path,
                line_start=finding.line_start,
                line_end=finding.line_end,
                symbol=finding.symbol,
                issue_kind=finding.issue_kind,
                region_hint=finding.region_hint,
                title=finding.title,
                evidence=finding.evidence,
                explanation=finding.explanation,
                suggested_follow_up=finding.suggested_follow_up,
                evidence_summary=finding.evidence,
            )
            for index, finding in enumerate(review_result.findings, start=1)
        ]
    )
