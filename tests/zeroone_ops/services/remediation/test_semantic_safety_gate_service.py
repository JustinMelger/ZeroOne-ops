"""Tests for the deterministic remediation semantic-safety gate."""

import pytest
from pydantic import ValidationError

from zeroone_ops.models.analysis import (
    AnalysisClassification,
    IssueAnalysis,
    SemanticSafetyAssessment,
)
from zeroone_ops.services.remediation.semantic_safety_gate_service import (
    SemanticSafetyGateService,
)


def _analysis(
    *,
    classification: AnalysisClassification = AnalysisClassification.AUTO_FIXABLE,
) -> IssueAnalysis:
    return IssueAnalysis(
        issue_key="finding-1",
        classification=classification,
        summary="Safe local change.",
        proposed_strategy="Apply one local edit.",
        semantic_safety=SemanticSafetyAssessment(
            current_behavior="The current code returns the wrong local value.",
            intended_behavior="The local condition returns the intended value.",
            preservation_evidence=["The edit remains within the reported file."],
        ),
    )


def test_gate_accepts_well_formed_auto_fixable_assessment() -> None:
    decision = SemanticSafetyGateService().decide(_analysis())

    assert decision.accepted is True
    assert decision.reason is None
    assert decision.assessment is not None


def test_gate_rejects_manual_analysis_without_edit_generation() -> None:
    decision = SemanticSafetyGateService().decide(
        _analysis(classification=AnalysisClassification.MANUAL)
    )

    assert decision.accepted is False
    assert decision.reason == "Manual analysis classification requires operator handling."


def test_invalid_evidence_uses_change_rationale_wording_without_claiming_unsafety():
    analysis = _analysis()
    invalid = analysis.semantic_safety.model_copy(update={"current_behavior": " "})
    decision = SemanticSafetyGateService().decide(
        analysis.model_copy(update={"semantic_safety": invalid})
    )
    assert not decision.accepted
    assert decision.reason == (
        "Change rationale is invalid: Value error, Change rationale text must not be blank."
    )
    assert decision.assessment is None


@pytest.mark.parametrize(
    "assessment",
    [
        {"current_behavior": "", "intended_behavior": "Target", "preservation_evidence": ["Proof"]},
        {
            "current_behavior": "Current",
            "intended_behavior": "",
            "preservation_evidence": ["Proof"],
        },
        {"current_behavior": "Current", "intended_behavior": "Target", "preservation_evidence": []},
        {
            "current_behavior": "Current",
            "intended_behavior": "Target",
            "preservation_evidence": [" "],
        },
    ],
)
def test_assessment_requires_bounded_non_empty_evidence(assessment: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SemanticSafetyAssessment.model_validate(assessment)
