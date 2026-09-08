"""Tests for remediation publication request rendering."""

from zeroone_ops.models.analysis import SemanticSafetyAssessment
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.services.remediation.publication_request_builder import (
    RemediationPublicationRequestBuilder,
)


def test_description_renders_semantic_safety_for_accepted_work() -> None:
    description = RemediationPublicationRequestBuilder.build_description(
        selected_issue=RemediationExecutionTarget(
            item_id="finding-1",
            source_type="ruff-sarif",
            source_ref="src/app.py::lint::E501",
            title="E501 in app.py",
            status="OPEN",
            message="Line too long.",
            file_path="src/app.py",
            line=8,
            rule_id="E501",
            severity="medium",
        ),
        change_summary="Wrap the local expression without changing its result.",
        semantic_safety=SemanticSafetyAssessment(
            current_behavior="The expression exceeds the configured line limit.",
            intended_behavior="The same expression is wrapped across lines.",
            preservation_evidence=["The expression and evaluated values are unchanged."],
        ),
    )

    assert "## Semantic Safety" in description
    assert "- Current behavior: The expression exceeds the configured line limit." in description
    assert "- Intended behavior: The same expression is wrapped across lines." in description
    assert "  - The expression and evaluated values are unchanged." in description
