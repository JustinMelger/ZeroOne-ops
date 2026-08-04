"""Review candidate generation service."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    CandidateAnnotation,
    CandidateReviewFinding,
    CandidateReviewResult,
    CandidateValidationFlag,
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
    forwarded_candidate_ids: tuple[str, ...]
    pre_precision_dropped_candidates: tuple[DroppedCandidate, ...]
    candidate_annotations: tuple[CandidateAnnotation, ...]
    message: str


class ReviewCandidateGenerationService:
    """Generate non-authoritative review candidates and annotate them deterministically."""

    def __init__(
        self,
        config: AppConfig,
        llm_client_builder: Callable[[], FixtureLLMClient | OpenAILLMClient | None] | None = None,
    ) -> None:
        """Initialize the candidate review service."""
        self.config = config
        self._llm_client_builder = llm_client_builder

    def analyze(self, context: ChangeRequestReviewContext) -> ReviewCandidateStageResult:
        """Generate candidate findings, then annotate them without deciding final truth."""
        llm_client = self._build_llm_client()
        if llm_client is None:
            return ReviewCandidateStageResult(
                candidate_result=None,
                raw_review_result=None,
                forwarded_candidate_ids=(),
                pre_precision_dropped_candidates=(),
                candidate_annotations=(),
                message="LLM backend not configured for change-request review.",
            )

        try:
            raw_review_result = llm_client.review_merge_request(context)
        except LLMClientError as error:
            return ReviewCandidateStageResult(
                candidate_result=None,
                raw_review_result=None,
                forwarded_candidate_ids=(),
                pre_precision_dropped_candidates=(),
                candidate_annotations=(),
                message=f"Structured change-request review failed: {error}",
            )

        candidate_result = _candidate_review_result_from_review_result(raw_review_result)
        candidate_ids, candidate_annotations = _annotate_candidate_findings(
            context=context,
            candidate_result=candidate_result,
        )

        return ReviewCandidateStageResult(
            candidate_result=candidate_result,
            raw_review_result=raw_review_result,
            forwarded_candidate_ids=tuple(candidate_ids),
            pre_precision_dropped_candidates=(),
            candidate_annotations=tuple(candidate_annotations),
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


def _annotate_candidate_findings(
    *,
    context: ChangeRequestReviewContext,
    candidate_result: CandidateReviewResult,
) -> tuple[list[str], list[CandidateAnnotation]]:
    """Annotate candidate findings without suppressing them before precision."""
    reviewed_files = {
        changed_file.file_path: changed_file for changed_file in context.changed_files
    }

    candidate_annotations: list[CandidateAnnotation] = []
    for candidate in candidate_result.findings:
        annotation = _build_candidate_annotation(
            candidate=candidate,
            reviewed_files=reviewed_files,
        )
        if annotation is not None:
            candidate_annotations.append(annotation)

    candidate_ids = [candidate.candidate_id for candidate in candidate_result.findings]
    return candidate_ids, candidate_annotations


def _build_candidate_annotation(
    *,
    candidate: CandidateReviewFinding,
    reviewed_files: dict[str, ReviewFileContext],
) -> CandidateAnnotation | None:
    """Return advisory validation annotations for one candidate when applicable."""
    flags: list[CandidateValidationFlag] = []
    notes: list[str] = []

    reviewed_file = reviewed_files.get(candidate.file_path)
    if reviewed_file is None:
        flags.append("off_diff")
        notes.append("Candidate references a file outside the reviewed diff.")
        return CandidateAnnotation(
            candidate_id=candidate.candidate_id,
            flags=flags,
            notes=notes,
        )

    evidence = candidate.evidence.strip()
    if len(evidence) < 20:
        flags.append("weak_evidence")
        notes.append("Candidate evidence is too short to ground safely.")
        return CandidateAnnotation(
            candidate_id=candidate.candidate_id,
            flags=flags,
            notes=notes,
        )

    normalized_evidence = evidence.lower()
    if normalized_evidence in _GENERIC_EVIDENCE_MARKERS:
        flags.extend(["weak_evidence", "generic_evidence"])
        notes.append("Candidate evidence is too generic to ground safely.")
        return CandidateAnnotation(
            candidate_id=candidate.candidate_id,
            flags=flags,
            notes=notes,
        )

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
        flags.extend(["weak_evidence", "ungrounded_wording"])
        notes.append("Candidate has no grounded tokens in the reviewed context.")
        return CandidateAnnotation(
            candidate_id=candidate.candidate_id,
            flags=flags,
            notes=notes,
        )
    if not evidence_matches_reviewed_text and not any(
        token in reviewed_tokens for token in grounding_tokens
    ):
        flags.extend(["weak_evidence", "ungrounded_wording"])
        notes.append("Candidate wording is not grounded in the reviewed context.")
        return CandidateAnnotation(
            candidate_id=candidate.candidate_id,
            flags=flags,
            notes=notes,
        )
    if _is_speculative_or_low_signal(candidate):
        flags.extend(_speculative_or_low_signal_flags(candidate))
        notes.append("Candidate is too speculative or low-signal to publish.")
        return CandidateAnnotation(
            candidate_id=candidate.candidate_id,
            flags=flags,
            notes=notes,
        )
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
    return not any(marker in follow_up for marker in _ACTIONABLE_FOLLOW_UP_MARKERS)


def _speculative_or_low_signal_flags(
    candidate: CandidateReviewFinding,
) -> list[CandidateValidationFlag]:
    """Return the advisory flags that explain a speculative or low-signal candidate."""
    explanation = candidate.explanation.strip().lower()
    follow_up = candidate.suggested_follow_up.strip().lower()
    flags: list[CandidateValidationFlag] = []

    if any(marker in explanation for marker in _LOW_SIGNAL_EXPLANATION_MARKERS):
        flags.append("speculative_explanation")
    elif any(marker in explanation for marker in _SPECULATIVE_MARKERS) and not any(
        token in explanation
        for token in ("will", "would", "break", "regression", "missing", "unsafe")
    ):
        flags.append("speculative_explanation")

    if not any(marker in follow_up for marker in _ACTIONABLE_FOLLOW_UP_MARKERS):
        flags.append("low_signal_follow_up")

    if not flags:
        flags.append("weak_evidence")
    return flags


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
