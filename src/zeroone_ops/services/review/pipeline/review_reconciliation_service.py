"""Review reconciliation service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    CandidateReviewFinding,
    ChangeRequestReviewContext,
    ContinuityStatus,
    DroppedCandidate,
    OverlapPacket,
    OverlapReconciliationResult,
    PrecisionAcceptedFinding,
    PrecisionReviewDecision,
    ReconciledReviewDecision,
    ReviewFinding,
    ReviewResult,
)
from zeroone_ops.providers.llm_client import (
    FixtureLLMClient,
    LLMClientError,
    OpenAILLMClient,
)
from zeroone_ops.services.review.continuity.review_overlap_analysis_service import (
    ReviewOverlapAnalysisService,
)
from zeroone_ops.services.review.continuity.review_overlap_packet_builder import (
    OverlapPacketBuilder,
)
from zeroone_ops.services.review.pipeline.review_candidate_generation_service import (
    ReviewCandidateStageResult,
)
from zeroone_ops.services.review.pipeline.review_reconciled_decision_builder import (
    build_reconciled_review_decision,
)
from zeroone_ops.settings import SettingsError, load_openai_connection_config
from zeroone_ops.utils.clock import now_utc


@dataclass(frozen=True)
class ReviewReconciliationResult:
    """Capture the outcome of reconciliation and final review meaning."""

    review_result: ReviewResult | None
    reconciled_decision: ReconciledReviewDecision | None
    precision_decision: PrecisionReviewDecision | None
    overlap_result: OverlapReconciliationResult | None
    message: str


class ReviewReconciliationService:
    """Own final review meaning and continuity outcomes for one review pass."""

    def __init__(
        self,
        config: AppConfig,
        llm_client_builder: Callable[[], FixtureLLMClient | OpenAILLMClient | None] | None = None,
    ) -> None:
        """Initialize the review reconciliation service."""
        self.config = config
        self._llm_client_builder = llm_client_builder

    def reconcile(
        self,
        *,
        context: ChangeRequestReviewContext,
        candidate_stage_result: ReviewCandidateStageResult,
    ) -> ReviewReconciliationResult:
        """Reconcile candidate-stage output into final review meaning."""
        raw_review_result = candidate_stage_result.raw_review_result
        if raw_review_result is None:
            return ReviewReconciliationResult(
                review_result=None,
                reconciled_decision=None,
                precision_decision=None,
                overlap_result=None,
                message=candidate_stage_result.message,
            )

        llm_client = self._build_llm_client()
        if llm_client is None:
            return ReviewReconciliationResult(
                review_result=None,
                reconciled_decision=None,
                precision_decision=None,
                overlap_result=None,
                message="LLM backend not configured for review reconciliation.",
            )

        candidate_result = candidate_stage_result.candidate_result
        active_candidates = [] if candidate_result is None else list(candidate_result.findings)
        overlap_packet = self._build_precision_overlap_packet(
            context=context,
            active_candidates=active_candidates,
        )
        try:
            precision_decision = llm_client.review_precision_reconciliation(
                context,
                candidates=active_candidates,
                candidate_annotations=list(candidate_stage_result.candidate_annotations),
                overlap_packet=overlap_packet,
                candidate_stage_summary=raw_review_result.summary,
                candidate_stage_classification=raw_review_result.classification,
                candidate_stage_rationale=(
                    raw_review_result.review_confidence_reason or raw_review_result.summary
                ),
                max_findings=self.config.review.max_findings_per_review,
            )
        except LLMClientError as error:
            return ReviewReconciliationResult(
                review_result=None,
                reconciled_decision=None,
                precision_decision=None,
                overlap_result=None,
                message=f"Review precision reconciliation failed: {error}",
            )

        reconciled_decision = self._normalize_precision_decision(
            context=context,
            precision_decision=precision_decision,
            active_candidates=active_candidates,
            pre_precision_dropped_candidates=(
                candidate_stage_result.pre_precision_dropped_candidates
            ),
        )
        review_result = reconciled_decision.to_review_result()
        overlap_result = self._reconcile_overlap(context=context, review_result=review_result)
        self._attach_continuity_outcomes(
            decision=reconciled_decision,
            overlap_result=overlap_result,
        )
        review_result = reconciled_decision.to_review_result()

        return ReviewReconciliationResult(
            review_result=review_result,
            reconciled_decision=reconciled_decision,
            precision_decision=precision_decision,
            overlap_result=overlap_result,
            message=(
                f"Reconciled review classification: {review_result.classification}. "
                f"Accepted findings: {len(reconciled_decision.accepted_findings)}."
            ),
        )

    def _build_llm_client(self) -> FixtureLLMClient | OpenAILLMClient | None:
        """Build the configured review LLM client for the precision stage."""
        if self._llm_client_builder is not None:
            return self._llm_client_builder()
        try:
            return OpenAILLMClient(load_openai_connection_config(), solution_output_path=None)
        except SettingsError:
            return None

    def _normalize_precision_decision(
        self,
        *,
        context: ChangeRequestReviewContext,
        precision_decision: PrecisionReviewDecision,
        active_candidates: list[CandidateReviewFinding],
        pre_precision_dropped_candidates: tuple[DroppedCandidate, ...],
    ) -> ReconciledReviewDecision:
        """Validate and normalize precision output into the final decision contract."""
        active_candidates_by_id = {
            candidate.candidate_id: candidate for candidate in active_candidates
        }
        active_candidate_ids = set(active_candidates_by_id)

        accepted_source_id_list: list[str] = []
        accepted_source_ids: set[str] = set()
        for finding in precision_decision.accepted_findings:
            source_ids = set(finding.source_candidate_ids)
            if not source_ids or not source_ids.issubset(active_candidate_ids):
                return self._invalid_precision_fallback(
                    context=context,
                    message=(
                        "Precision pass returned accepted findings with unsupported "
                        "candidate lineage."
                    ),
                    dropped_candidates=pre_precision_dropped_candidates,
                )
            accepted_source_id_list.extend(finding.source_candidate_ids)
            accepted_source_ids.update(source_ids)
        if len(accepted_source_id_list) != len(set(accepted_source_id_list)):
            return self._invalid_precision_fallback(
                context=context,
                message=(
                    "Precision pass assigned the same candidate to multiple accepted findings."
                ),
                dropped_candidates=pre_precision_dropped_candidates,
            )

        dropped_candidate_id_list = [
            candidate.candidate_id for candidate in precision_decision.dropped_candidates
        ]
        dropped_candidate_ids = {candidate_id for candidate_id in dropped_candidate_id_list}
        if not dropped_candidate_ids.issubset(active_candidate_ids):
            return self._invalid_precision_fallback(
                context=context,
                message="Precision pass returned dropped candidates outside the candidate set.",
                dropped_candidates=pre_precision_dropped_candidates,
            )
        if len(dropped_candidate_id_list) != len(dropped_candidate_ids):
            return self._invalid_precision_fallback(
                context=context,
                message="Precision pass dropped the same candidate more than once.",
                dropped_candidates=pre_precision_dropped_candidates,
            )
        if accepted_source_ids & dropped_candidate_ids:
            return self._invalid_precision_fallback(
                context=context,
                message=("Precision pass both retained and dropped the same candidate."),
                dropped_candidates=pre_precision_dropped_candidates,
            )

        if precision_decision.review_classification == "findings_present":
            if not precision_decision.accepted_findings:
                return self._invalid_precision_fallback(
                    context=context,
                    message="Precision pass declared findings_present without accepted findings.",
                    dropped_candidates=pre_precision_dropped_candidates,
                )
        elif precision_decision.accepted_findings:
            return self._invalid_precision_fallback(
                context=context,
                message=(
                    "Precision pass returned accepted findings with a non-findings classification."
                ),
                dropped_candidates=pre_precision_dropped_candidates,
            )

        covered_candidate_ids = accepted_source_ids | dropped_candidate_ids
        if covered_candidate_ids != active_candidate_ids:
            return self._invalid_precision_fallback(
                context=context,
                message=("Precision pass did not account for every candidate explicitly."),
                dropped_candidates=pre_precision_dropped_candidates,
            )

        truncated_precision_decision = self._truncate_precision_findings(precision_decision)
        truncated_precision_decision = truncated_precision_decision.model_copy(
            update={
                "advisory_notes": _normalize_advisory_notes(
                    truncated_precision_decision.advisory_notes
                )
            }
        )
        reconciled_decision = build_reconciled_review_decision(
            truncated_precision_decision,
            prior_review_context_used=bool(
                context.prior_review_context and context.prior_review_context.passes
            ),
            same_sha_review=self._is_same_sha_review(context),
            repair_allowed=truncated_precision_decision.review_classification
            != "manual_review_only",
            reconciled_at=now_utc(),
            pipeline_version="review-staged-v1",
        )
        reconciled_decision.dropped_candidates = [
            *pre_precision_dropped_candidates,
            *reconciled_decision.dropped_candidates,
        ]
        return reconciled_decision

    def _truncate_precision_findings(
        self,
        precision_decision: PrecisionReviewDecision,
    ) -> PrecisionReviewDecision:
        """Enforce the retained-finding cap without reintroducing a second path."""
        sorted_accepted_findings = sorted(
            precision_decision.accepted_findings,
            key=self._precision_finding_sort_key,
        )
        max_findings = self.config.review.max_findings_per_review
        if len(sorted_accepted_findings) <= max_findings:
            return precision_decision.model_copy(
                update={"accepted_findings": sorted_accepted_findings}
            )

        retained_findings = sorted_accepted_findings[:max_findings]
        overflow_findings = sorted_accepted_findings[max_findings:]
        overflow_drops = [
            DroppedCandidate(
                candidate_id=candidate_id,
                drop_reason="superseded",
                notes="Accepted finding exceeded the maximum retained findings for this pass.",
            )
            for finding in overflow_findings
            for candidate_id in finding.source_candidate_ids
        ]
        return precision_decision.model_copy(
            update={
                "accepted_findings": retained_findings,
                "dropped_candidates": [
                    *precision_decision.dropped_candidates,
                    *overflow_drops,
                ],
            }
        )

    def _build_precision_overlap_packet(
        self,
        *,
        context: ChangeRequestReviewContext,
        active_candidates: list[CandidateReviewFinding],
    ) -> OverlapPacket | None:
        """Build bounded overlap hints for the precision prompt when candidates exist."""
        if not active_candidates:
            return None
        provisional_review_result = ReviewResult(
            classification="findings_present",
            summary="Candidate findings awaiting precision review.",
            findings=[
                ReviewFinding(
                    severity=candidate.severity,
                    file_path=candidate.file_path,
                    line_start=candidate.line_start,
                    line_end=candidate.line_end,
                    symbol=candidate.symbol,
                    issue_kind=candidate.issue_kind,
                    region_hint=candidate.region_hint,
                    title=candidate.title,
                    evidence=candidate.evidence,
                    explanation=candidate.explanation,
                    suggested_follow_up=candidate.suggested_follow_up,
                )
                for candidate in active_candidates
            ],
        )
        return OverlapPacketBuilder().build(
            context=context,
            review_result=provisional_review_result,
        )

    def _invalid_precision_fallback(
        self,
        *,
        context: ChangeRequestReviewContext,
        message: str,
        dropped_candidates: tuple[DroppedCandidate, ...],
    ) -> ReconciledReviewDecision:
        """Fallback to manual review when the precision output is internally invalid."""
        return ReconciledReviewDecision(
            review_classification="manual_review_only",
            decision_summary=(
                "The automated reconciliation step could not produce a trustworthy final "
                "review decision and was downgraded to manual review."
            ),
            decision_rationale=message,
            confidence_level=0.0,
            accepted_findings=[],
            advisory_notes=[],
            dropped_candidates=list(dropped_candidates),
            prior_review_context_used=bool(
                context.prior_review_context and context.prior_review_context.passes
            ),
            same_sha_review=self._is_same_sha_review(context),
            repair_allowed=False,
            reconciled_at=now_utc(),
            pipeline_version="review-staged-v1",
        )

    def _reconcile_overlap(
        self,
        *,
        context: ChangeRequestReviewContext,
        review_result: ReviewResult,
    ) -> OverlapReconciliationResult | None:
        """Resolve repeated-review overlap when prior review context exists."""
        overlap_packet = OverlapPacketBuilder().build(
            context=context,
            review_result=review_result,
        )
        if overlap_packet is None:
            return None

        overlap_analysis = ReviewOverlapAnalysisService(self.config).analyze(overlap_packet)
        return overlap_analysis.overlap_result

    def _attach_continuity_outcomes(
        self,
        *,
        decision: ReconciledReviewDecision,
        overlap_result: OverlapReconciliationResult | None,
    ) -> None:
        """Attach continuity outcomes to accepted findings when available."""
        if overlap_result is None:
            return

        status_by_index: dict[int, ContinuityStatus] = {}
        for resolution in overlap_result.resolutions:
            current_index = resolution.current_finding_index
            if current_index is None:
                continue
            if resolution.outcome == "still_unresolved":
                status_by_index[current_index] = "unresolved"
            elif resolution.outcome == "new_in_this_pass":
                status_by_index[current_index] = "new"

        for index, finding in enumerate(decision.accepted_findings):
            finding.continuity_status = status_by_index.get(index)

    def _is_same_sha_review(self, context: ChangeRequestReviewContext) -> bool:
        """Return whether the latest prior pass used the same reviewed SHA."""
        prior_review_context = context.prior_review_context
        if prior_review_context is None or not prior_review_context.passes:
            return False
        return prior_review_context.passes[0].reviewed_head_sha == context.head_sha

    def _precision_finding_sort_key(
        self,
        finding: PrecisionAcceptedFinding,
    ) -> tuple[int, str, int, int, str]:
        """Sort precision findings deterministically before enforcing the cap."""
        return (
            _SEVERITY_RANK[finding.severity],
            finding.file_path,
            -1 if finding.line_start is None else finding.line_start,
            -1 if finding.line_end is None else finding.line_end,
            finding.title,
        )


_SEVERITY_RANK = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


def _normalize_advisory_notes(notes: list[str]) -> list[str]:
    """Return bounded developer-facing advisory notes."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_note in notes:
        note = raw_note.strip()
        if not note:
            continue
        folded = note.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        normalized.append(note)
        if len(normalized) == 3:
            break
    return normalized
