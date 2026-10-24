"""Test change-rationale presentation without changing internal assessment data."""

from zeroone_ops.models.analysis import SemanticSafetyAssessment
from zeroone_ops.models.work_item import WorkItemSemanticSafety
from zeroone_ops.services.remediation.semantic_safety_presentation import (
    render_semantic_safety_lines,
)


def test_empty_record_renders_no_section():
    assert render_semantic_safety_lines(WorkItemSemanticSafety()) == []


def test_rejection_without_assessment_explains_missing_rationale():
    lines = render_semantic_safety_lines(
        WorkItemSemanticSafety(rejection_reason="Required explanation is incomplete.")
    )
    assert "## Change Rationale" in lines
    assert "- Why remediation stopped: Required explanation is incomplete." in lines
    assert "No change rationale was available." in lines


def test_rationale_preserves_untrusted_text_and_existing_escaping():
    assessment = SemanticSafetyAssessment(
        current_behavior="A <tag>\n[link](https://example) **claim**",
        intended_behavior="Keep _values_ unchanged.",
        preservation_evidence=["No <script> instructions."],
    )
    before = assessment.model_dump()
    body = "\n".join(render_semantic_safety_lines(assessment))
    assert "Model-provided explanation; not independent verification." in body
    assert "See validation and review results." in body
    assert "- Current behavior: A &lt;tag&gt; \\[link\\](https://example) \\*\\*claim\\*\\*" in body
    assert "- Intended change: Keep \\_values\\_ unchanged." in body
    assert "- Why existing behavior should be preserved:" in body
    assert "  - No &lt;script&gt; instructions." in body
    assert assessment.model_dump() == before
