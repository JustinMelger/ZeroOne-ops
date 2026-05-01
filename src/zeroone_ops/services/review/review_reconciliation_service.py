"""Review reconciliation service."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    ContinuityStatus,
    MergeRequestReviewContext,
    OverlapReconciliationResult,
    ReconciledReviewDecision,
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
        review_result = candidate_stage_result.review_result
        if review_result is None:
            return ReviewReconciliationResult(
                review_result=None,
                reconciled_decision=None,
                overlap_result=None,
                message=candidate_stage_result.message,
            )

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

    def _attach_candidate_provenance(
        self,
        *,
        decision: ReconciledReviewDecision,
        candidate_stage_result: ReviewCandidateStageResult,
    ) -> None:
        """Attach candidate-stage provenance to the reconciled decision."""
        decision.dropped_candidates = list(candidate_stage_result.dropped_candidates)
        accepted_ids = list(candidate_stage_result.accepted_candidate_ids)
        for index, finding in enumerate(decision.accepted_findings):
            if index < len(accepted_ids):
                finding.source_candidate_ids = [accepted_ids[index]]

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
