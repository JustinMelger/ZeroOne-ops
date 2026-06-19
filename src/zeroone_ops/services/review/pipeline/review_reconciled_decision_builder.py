"""Build canonical reconciled review decisions from precision output."""

from __future__ import annotations

from datetime import datetime

from zeroone_ops.models.review import (
    DiffReference,
    PrecisionReviewDecision,
    ReconciledFinding,
    ReconciledReviewDecision,
    ReviewFinding,
)
from zeroone_ops.utils.review_finding_identity import (
    build_legacy_review_finding_identity,
    build_review_finding_identity,
)


def build_reconciled_review_decision(
    precision_decision: PrecisionReviewDecision,
    *,
    prior_review_context_used: bool,
    same_sha_review: bool,
    repair_allowed: bool,
    reconciled_at: datetime,
    pipeline_version: str,
) -> ReconciledReviewDecision:
    """Adapt the precision-pass output into the staged reconciliation contract."""
    accepted_findings: list[ReconciledFinding] = []
    for index, finding in enumerate(
        precision_decision.accepted_findings,
        start=1,
    ):
        scaffold = ReviewFinding(
            severity=finding.severity,
            file_path=finding.file_path,
            line_start=finding.line_start,
            line_end=finding.line_end,
            symbol=finding.symbol,
            issue_kind=finding.issue_kind,
            region_hint=finding.region_hint,
            title=finding.title,
            evidence=finding.evidence[0] if finding.evidence else "",
            explanation=finding.why_it_matters,
            suggested_follow_up=finding.recommended_follow_up or "",
        )
        accepted_findings.append(
            ReconciledFinding(
                finding_id=f"finding-{index}",
                severity=finding.severity,
                file_path=finding.file_path,
                line_start=finding.line_start,
                line_end=finding.line_end,
                symbol=finding.symbol,
                issue_kind=finding.issue_kind,
                region_hint=finding.region_hint,
                title=finding.title,
                summary=finding.summary,
                evidence=list(finding.evidence),
                diff_references=[
                    DiffReference(
                        file_path=finding.file_path,
                        start_line=finding.line_start,
                        end_line=finding.line_end,
                    )
                ],
                file_paths=[finding.file_path],
                why_it_matters=finding.why_it_matters,
                recommended_follow_up=finding.recommended_follow_up,
                stable_identity=build_review_finding_identity(scaffold),
                legacy_identity=build_legacy_review_finding_identity(scaffold),
                source_candidate_ids=list(finding.source_candidate_ids),
            )
        )

    return ReconciledReviewDecision(
        review_classification=precision_decision.review_classification,
        decision_summary=precision_decision.decision_summary,
        decision_rationale=precision_decision.decision_rationale,
        confidence_level=precision_decision.confidence_level,
        accepted_findings=accepted_findings,
        advisory_notes=list(precision_decision.advisory_notes),
        dropped_candidates=list(precision_decision.dropped_candidates),
        prior_review_context_used=prior_review_context_used,
        same_sha_review=same_sha_review,
        repair_allowed=repair_allowed,
        reconciled_at=reconciled_at,
        pipeline_version=pipeline_version,
    )
