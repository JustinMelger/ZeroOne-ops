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
    """Apply structural semantic-safety requirements without judging correctness.

    Acceptance confirms only that the analysis provides bounded current behavior,
    intended behavior, and preservation evidence. It is not proof that the claim
    is true or that a generated edit preserves behavior; validation and review
    remain responsible for assessing the resulting change.
    """

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
