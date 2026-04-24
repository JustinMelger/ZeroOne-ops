"""Review analysis service."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.review import (
    MergeRequestReviewContext,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from ai_sonar_bot.providers.llm_client import FixtureLLMClient, LLMClientError, OpenAILLMClient
from ai_sonar_bot.settings import SettingsError, load_openai_connection_config

_GENERIC_EVIDENCE_MARKERS = frozenset(
    {
        "this change",
        "the change",
        "this diff",
        "the diff",
        "code snippet",
        "source context",
    }
)
_SPECULATIVE_MARKERS = frozenset(
    {
        "may",
        "might",
        "could",
        "possibly",
        "potentially",
        "perhaps",
        "appears to",
        "seems to",
    }
)
_LOW_SIGNAL_EXPLANATION_MARKERS = frozenset(
    {
        "may be risky",
        "might be risky",
        "could be risky",
        "potential issue",
        "possible issue",
        "needs review",
        "should be reviewed",
        "worth checking",
    }
)
_ACTIONABLE_FOLLOW_UP_MARKERS = frozenset(
    {
        "add",
        "define",
        "delete",
        "remove",
        "rename",
        "replace",
        "restore",
        "guard",
        "handle",
        "update",
        "assert",
        "test",
        "validate",
        "check",
        "prevent",
        "cover",
    }
)
_SEVERITY_RANK = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


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

        review_result = _validated_review_result(
            context=context,
            review_result=review_result,
            max_findings=self.config.review.max_findings_per_review,
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


def _validated_review_result(
    *,
    context: MergeRequestReviewContext,
    review_result: ReviewResult,
    max_findings: int,
) -> ReviewResult:
    """Drop review findings that are not grounded in the reviewed context."""
    if review_result.classification != "findings_present":
        return review_result

    reviewed_files = {
        changed_file.file_path: changed_file for changed_file in context.changed_files
    }
    validated_findings = [
        finding
        for finding in review_result.findings
        if _is_grounded_finding(finding=finding, reviewed_files=reviewed_files)
    ]
    if validated_findings:
        ranked_findings = sorted(
            validated_findings,
            key=lambda finding: (
                _SEVERITY_RANK[finding.severity],
                finding.file_path,
                finding.title,
            ),
        )
        limited_findings = ranked_findings[:max_findings]
        return ReviewResult(
            classification="findings_present",
            summary=review_result.summary,
            review_confidence=review_result.review_confidence,
            review_confidence_reason=review_result.review_confidence_reason,
            findings=limited_findings,
        )
    return ReviewResult(
        classification="no_findings",
        summary="No actionable findings after review validation.",
        review_confidence=review_result.review_confidence,
        review_confidence_reason=review_result.review_confidence_reason,
        findings=[],
    )


def _is_grounded_finding(
    *,
    finding: ReviewFinding,
    reviewed_files: dict[str, ReviewFileContext],
) -> bool:
    """Return whether one finding stays tied to reviewed file context."""
    reviewed_file = reviewed_files.get(finding.file_path)
    if reviewed_file is None:
        return False
    evidence = finding.evidence.strip()
    if len(evidence) < 20:
        return False
    normalized_evidence = evidence.lower()
    if normalized_evidence in _GENERIC_EVIDENCE_MARKERS:
        return False
    reviewed_text = "\n".join(
        [
            reviewed_file.diff or "",
            reviewed_file.content,
            reviewed_file.file_path,
        ]
    ).lower()
    quoted_fragments = [
        fragment.strip().lower()
        for fragment in re.findall(r"`([^`]+)`", evidence)
        if fragment.strip()
    ]
    if any(fragment in reviewed_text for fragment in quoted_fragments):
        evidence_matches_reviewed_text = True
    else:
        evidence_matches_reviewed_text = False
    grounding_text = " ".join(
        [
            finding.title,
            finding.evidence,
            finding.explanation,
        ]
    )
    reviewed_tokens = _grounding_tokens(reviewed_text)
    grounding_tokens = _grounding_tokens(grounding_text)
    if not grounding_tokens and not evidence_matches_reviewed_text:
        return False
    if not evidence_matches_reviewed_text and not any(
        token in reviewed_tokens for token in grounding_tokens
    ):
        return False
    if _is_speculative_or_low_signal(finding):
        return False
    return True


def _is_speculative_or_low_signal(finding: ReviewFinding) -> bool:
    """Return whether one finding is too weak or speculative to publish."""
    explanation = finding.explanation.strip().lower()
    follow_up = finding.suggested_follow_up.strip().lower()
    if any(marker in explanation for marker in _LOW_SIGNAL_EXPLANATION_MARKERS):
        return True
    explanation_tokens = re.findall(r"[a-z']+", explanation)
    if any(marker in explanation for marker in _SPECULATIVE_MARKERS) and not any(
        token in explanation
        for token in ("will", "would", "break", "regression", "missing", "unsafe")
    ):
        return True
    if len(explanation_tokens) < 6:
        return True
    if not any(marker in follow_up for marker in _ACTIONABLE_FOLLOW_UP_MARKERS):
        return True
    return False


def _grounding_tokens(text: str) -> set[str]:
    """Extract lightly normalized tokens for grounding checks."""
    tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9_./:=`-]{4,}", text.lower()):
        if token in {"this", "that", "with", "from", "into", "without"}:
            continue
        normalized = _normalize_grounding_token(token)
        if len(normalized) >= 4:
            tokens.add(normalized)
    return tokens


def _normalize_grounding_token(token: str) -> str:
    """Lightly normalize tokens so close paraphrases still match code-backed text."""
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    return token
