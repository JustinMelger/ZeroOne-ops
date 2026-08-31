"""Deterministically validate required semantic-safety assessment shape."""

from __future__ import annotations

from pydantic import ValidationError

from zeroone_ops.models.analysis import (
    AnalysisClassification,
    IssueAnalysis,
    SemanticSafetyAssessment,
    SemanticSafetyDecision,
)


class SemanticSafetyGateService:
    """Apply structural semantic-safety requirements without judging correctness."""

    def decide(self, analysis: IssueAnalysis) -> SemanticSafetyDecision:
        """Return whether one analysis may proceed to structured-edit generation."""
        if analysis.classification == AnalysisClassification.MANUAL:
            return SemanticSafetyDecision(
                accepted=False,
                reason="Manual analysis classification requires operator handling.",
                assessment=analysis.semantic_safety,
            )
        try:
            assessment = SemanticSafetyAssessment.model_validate(
                analysis.semantic_safety.model_dump()
            )
        except ValidationError as error:
            return SemanticSafetyDecision(
                accepted=False,
                reason=f"Semantic-safety assessment is invalid: {error.errors()[0]['msg']}",
            )
        return SemanticSafetyDecision(accepted=True, assessment=assessment)
