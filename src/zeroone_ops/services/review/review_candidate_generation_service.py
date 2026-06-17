"""Review candidate generation service."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    CandidateDropReason,
    CandidateReviewFinding,
    CandidateReviewResult,
    ChangeRequestReviewContext,
    DroppedCandidate,
    ReviewFileContext,
    ReviewResult,
)
from zeroone_ops.providers.llm_client import (
    FixtureLLMClient,
    LLMClientError,
    OpenAILLMClient,
)
from zeroone_ops.settings import SettingsError, load_openai_connection_config

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


@dataclass(frozen=True)
class ReviewCandidateStageResult:
    """Capture the explicit candidate-stage outcome for one review pass."""

    candidate_result: CandidateReviewResult | None
    raw_review_result: ReviewResult | None
    accepted_candidate_ids: tuple[str, ...]
    dropped_candidates: tuple[DroppedCandidate, ...]
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
                accepted_candidate_ids=(),
                dropped_candidates=(),
                message="LLM backend not configured for change-request review.",
            )

        try:
            raw_review_result = llm_client.review_merge_request(context)
        except LLMClientError as error:
            return ReviewCandidateStageResult(
                candidate_result=None,
                raw_review_result=None,
                accepted_candidate_ids=(),
                dropped_candidates=(),
                message=f"Structured change-request review failed: {error}",
            )

        candidate_result = _candidate_review_result_from_review_result(raw_review_result)
        accepted_candidate_ids, dropped_candidates = _ground_candidate_findings(
            context=context,
            candidate_result=candidate_result,
        )

        return ReviewCandidateStageResult(
            candidate_result=candidate_result,
            raw_review_result=raw_review_result,
            accepted_candidate_ids=tuple(accepted_candidate_ids),
            dropped_candidates=tuple(dropped_candidates),
            message=(
                "Candidate review generated "
                f"{len(candidate_result.findings)} candidates and accepted "
                f"{len(accepted_candidate_ids)} findings."
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


def _ground_candidate_findings(
    *,
    context: ChangeRequestReviewContext,
    candidate_result: CandidateReviewResult,
) -> tuple[list[str], list[DroppedCandidate]]:
    """Ground candidate findings without deciding final review truth."""
    reviewed_files = {
        changed_file.file_path: changed_file for changed_file in context.changed_files
    }

    accepted_candidates: list[CandidateReviewFinding] = []
    dropped_candidates: list[DroppedCandidate] = []
    for candidate in candidate_result.findings:
        validation = _validate_candidate_finding(candidate=candidate, reviewed_files=reviewed_files)
        if validation is None:
            accepted_candidates.append(candidate)
        else:
            drop_reason, notes = validation
            dropped_candidates.append(
                DroppedCandidate(
                    candidate_id=candidate.candidate_id,
                    drop_reason=drop_reason,
                    notes=notes,
                )
            )

    accepted_candidate_ids = [candidate.candidate_id for candidate in accepted_candidates]
    return accepted_candidate_ids, dropped_candidates


def _validate_candidate_finding(
    *,
    candidate: CandidateReviewFinding,
    reviewed_files: dict[str, ReviewFileContext],
) -> tuple[CandidateDropReason, str] | None:
    """Return drop metadata when one candidate is not grounded enough to keep."""
    reviewed_file = reviewed_files.get(candidate.file_path)
    if reviewed_file is None:
        return "off_diff", "Candidate references a file outside the reviewed diff."

    evidence = candidate.evidence.strip()
    if len(evidence) < 20:
        return "weak_evidence", "Candidate evidence is too short to ground safely."

    normalized_evidence = evidence.lower()
    if normalized_evidence in _GENERIC_EVIDENCE_MARKERS:
        return "weak_evidence", "Candidate evidence is too generic to ground safely."

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
    evidence_matches_reviewed_text = any(fragment in reviewed_text for fragment in quoted_fragments)
    grounding_text = " ".join(
        [
            candidate.title,
            candidate.evidence,
            candidate.explanation,
        ]
    )
    reviewed_tokens = _grounding_tokens(reviewed_text)
    grounding_tokens = _grounding_tokens(grounding_text)
    if not grounding_tokens and not evidence_matches_reviewed_text:
        return "weak_evidence", "Candidate has no grounded tokens in the reviewed context."
    if not evidence_matches_reviewed_text and not any(
        token in reviewed_tokens for token in grounding_tokens
    ):
        return "weak_evidence", "Candidate wording is not grounded in the reviewed context."
    if _is_speculative_or_low_signal(candidate):
        return "weak_evidence", "Candidate is too speculative or low-signal to publish."
    return None


def _is_speculative_or_low_signal(candidate: CandidateReviewFinding) -> bool:
    """Return whether one candidate is too weak or speculative to publish."""
    explanation = candidate.explanation.strip().lower()
    follow_up = candidate.suggested_follow_up.strip().lower()
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
