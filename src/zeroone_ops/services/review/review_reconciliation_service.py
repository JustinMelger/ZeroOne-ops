"""Review reconciliation service."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    CandidateReviewFinding,
    ContinuityStatus,
    DroppedCandidate,
    MergeRequestReviewContext,
    OverlapReconciliationResult,
    ReconciledReviewDecision,
    ReviewFinding,
    ReviewResult,
)
from zeroone_ops.services.review.review_candidate_service import ReviewCandidateStageResult
from zeroone_ops.services.review.review_overlap_analysis_service import (
    ReviewOverlapAnalysisService,
)
from zeroone_ops.services.review.review_overlap_packet_builder import OverlapPacketBuilder
from zeroone_ops.utils.clock import now_utc


@dataclass(frozen=True)
class ReviewReconciliationResult:
    """Capture the outcome of reconciliation and final review meaning."""

    review_result: ReviewResult | None
    reconciled_decision: ReconciledReviewDecision | None
    overlap_result: OverlapReconciliationResult | None
    message: str


@dataclass(frozen=True)
class _AuthoritativeReviewBuild:
    """Capture the authoritative review result plus direct candidate lineage."""

    review_result: ReviewResult
    retained_candidates: tuple[CandidateReviewFinding, ...]
    overflow_candidates: tuple[CandidateReviewFinding, ...]


class ReviewReconciliationService:
    """Own final review meaning and continuity outcomes for one review pass."""

    def __init__(self, config: AppConfig) -> None:
        """Initialize the review reconciliation service."""
        self.config = config

    def reconcile(
        self,
        *,
        context: MergeRequestReviewContext,
        candidate_stage_result: ReviewCandidateStageResult,
    ) -> ReviewReconciliationResult:
        """Reconcile candidate-stage output into final review meaning."""
        raw_review_result = candidate_stage_result.raw_review_result
        if raw_review_result is None:
            return ReviewReconciliationResult(
                review_result=None,
                reconciled_decision=None,
                overlap_result=None,
                message=candidate_stage_result.message,
            )

        authoritative_build = self._authoritative_review_build(
            raw_review_result=raw_review_result,
            candidate_stage_result=candidate_stage_result,
        )
        review_result = authoritative_build.review_result

        overlap_result = self._reconcile_overlap(context=context, review_result=review_result)
        prior_review_context_used = bool(
            context.prior_review_context and context.prior_review_context.passes
        )
        reconciled_decision = ReconciledReviewDecision.from_review_result(
            review_result,
            prior_review_context_used=prior_review_context_used,
            same_sha_review=self._is_same_sha_review(context),
            repair_allowed=review_result.classification != "manual_review_only",
            reconciled_at=now_utc(),
            pipeline_version="review-staged-v1",
        )
        self._attach_candidate_provenance(
            decision=reconciled_decision,
            candidate_stage_result=candidate_stage_result,
            retained_candidates=authoritative_build.retained_candidates,
            overflow_candidates=authoritative_build.overflow_candidates,
        )
        self._attach_continuity_outcomes(
            decision=reconciled_decision,
            overlap_result=overlap_result,
        )

        return ReviewReconciliationResult(
            review_result=review_result,
            reconciled_decision=reconciled_decision,
            overlap_result=overlap_result,
            message=(
                f"Reconciled review classification: {review_result.classification}. "
                f"Accepted findings: {len(reconciled_decision.accepted_findings)}."
            ),
        )

    def _reconcile_overlap(
        self,
        *,
        context: MergeRequestReviewContext,
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

    def _authoritative_review_build(
        self,
        *,
        raw_review_result: ReviewResult,
        candidate_stage_result: ReviewCandidateStageResult,
    ) -> _AuthoritativeReviewBuild:
        """Build the authoritative review result and candidate lineage."""
        if raw_review_result.classification != "findings_present":
            return _AuthoritativeReviewBuild(
                review_result=raw_review_result,
                retained_candidates=(),
                overflow_candidates=(),
            )

        candidate_result = candidate_stage_result.candidate_result
        if candidate_result is None:
            return _AuthoritativeReviewBuild(
                review_result=ReviewResult(
                    classification="no_findings",
                    summary="No actionable findings after review validation.",
                    review_confidence=raw_review_result.review_confidence,
                    review_confidence_reason=raw_review_result.review_confidence_reason,
                    findings=[],
                ),
                retained_candidates=(),
                overflow_candidates=(),
            )

        accepted_candidates = self._accepted_candidates(
            candidate_result.findings,
            candidate_stage_result.accepted_candidate_ids,
        )
        if not accepted_candidates:
            return _AuthoritativeReviewBuild(
                review_result=ReviewResult(
                    classification="no_findings",
                    summary="No actionable findings after review validation.",
                    review_confidence=raw_review_result.review_confidence,
                    review_confidence_reason=raw_review_result.review_confidence_reason,
                    findings=[],
                ),
                retained_candidates=(),
                overflow_candidates=(),
            )

        ranked_candidates = sorted(
            accepted_candidates,
            key=lambda candidate: (
                _SEVERITY_RANK[candidate.severity],
                candidate.file_path,
                candidate.title,
            ),
        )
        retained_candidates = tuple(ranked_candidates[: self.config.review.max_findings_per_review])
        overflow_candidates = tuple(ranked_candidates[self.config.review.max_findings_per_review :])
        return _AuthoritativeReviewBuild(
            review_result=ReviewResult(
                classification="findings_present",
                summary=raw_review_result.summary,
                review_confidence=raw_review_result.review_confidence,
                review_confidence_reason=raw_review_result.review_confidence_reason,
                findings=[
                    _review_finding_from_candidate(candidate) for candidate in retained_candidates
                ],
            ),
            retained_candidates=retained_candidates,
            overflow_candidates=overflow_candidates,
        )

    def _attach_candidate_provenance(
        self,
        *,
        decision: ReconciledReviewDecision,
        candidate_stage_result: ReviewCandidateStageResult,
        retained_candidates: tuple[CandidateReviewFinding, ...],
        overflow_candidates: tuple[CandidateReviewFinding, ...],
    ) -> None:
        """Attach candidate-stage provenance to the reconciled decision."""
        decision.dropped_candidates = list(candidate_stage_result.dropped_candidates)
        decision.dropped_candidates.extend(
            DroppedCandidate(
                candidate_id=candidate.candidate_id,
                drop_reason="superseded",
                notes="Candidate exceeded the maximum retained findings for this review pass.",
            )
            for candidate in overflow_candidates
        )
        for finding, candidate in zip(
            decision.accepted_findings,
            retained_candidates,
            strict=False,
        ):
            finding.source_candidate_ids = [candidate.candidate_id]

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

    def _is_same_sha_review(self, context: MergeRequestReviewContext) -> bool:
        """Return whether the latest prior pass used the same reviewed SHA."""
        prior_review_context = context.prior_review_context
        if prior_review_context is None or not prior_review_context.passes:
            return False
        return prior_review_context.passes[0].reviewed_head_sha == context.head_sha

    def _accepted_candidates(
        self,
        candidates: list[CandidateReviewFinding],
        accepted_candidate_ids: tuple[str, ...],
    ) -> list[CandidateReviewFinding]:
        """Return accepted candidates in the original candidate list order."""
        accepted_ids = set(accepted_candidate_ids)
        return [candidate for candidate in candidates if candidate.candidate_id in accepted_ids]


_SEVERITY_RANK = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


def _review_finding_from_candidate(candidate: CandidateReviewFinding) -> ReviewFinding:
    """Convert one accepted candidate into the authoritative review-finding shape."""
    return ReviewFinding(
        severity=candidate.severity,
        file_path=candidate.file_path,
        symbol=candidate.symbol,
        issue_kind=candidate.issue_kind,
        region_hint=candidate.region_hint,
        title=candidate.title,
        evidence=candidate.evidence,
        explanation=candidate.explanation,
        suggested_follow_up=candidate.suggested_follow_up,
    )
