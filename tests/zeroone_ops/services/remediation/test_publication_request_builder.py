"""Tests for remediation publication request rendering."""

import pytest

from zeroone_ops.models.analysis import (
    SemanticSafetyAssessment,
    ValidationCommandResult,
    ValidationComparison,
    ValidationResult,
)
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

    assert "## Change Rationale" in description
    assert "- Current behavior: The expression exceeds the configured line limit." in description
    assert "- Intended change: The same expression is wrapped across lines." in description
    assert "- Why existing behavior should be preserved:" in description
    assert "Model-provided explanation; not independent verification." in description
    assert "  - The expression and evaluated values are unchanged." in description


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("passed", "Validation passed"),
        ("baseline_preserved", "Validation baseline preserved"),
        ("empty", "No validation commands configured"),
        ("unavailable", "Validation evidence unavailable"),
        ("failed", "Validation failed"),
        ("inconsistent", "Validation failed"),
    ],
)
def test_validation_description_uses_execution_evidence(case, expected):
    command = ValidationCommandResult(
        command="uv run pytest",
        exit_code=1 if case in {"failed", "inconsistent", "baseline_preserved"} else 0,
        stdout="private command output",
        stderr="private error output",
        duration_ms=3,
    )
    validation = ValidationResult(
        passed=case not in {"failed", "baseline_preserved"},
        results=[] if case == "empty" else [command],
        summary="private summary",
    )
    comparison = (
        ValidationComparison(
            outcome="baseline_preserved",
            baseline=validation,
            post_edit=validation,
            baseline_failure_count=1,
        )
        if case == "baseline_preserved"
        else None
    )
    description = RemediationPublicationRequestBuilder.build_description(
        selected_issue=RemediationExecutionTarget(
            item_id="finding-1",
            source_type="ruff-sarif",
            source_ref="finding-1",
            title="Finding",
            status="OPEN",
            message="Reported issue",
            file_path="src/app.py",
        ),
        change_summary="Apply the local correction.",
        validation_result=None if case == "unavailable" else validation,
        validation_comparison=comparison,
    )
    assert f"- Status: {expected}" in description
    assert "## Change Rationale" not in description
    assert "private" not in description
    if case not in {"empty", "unavailable"}:
        assert "- Commands: `uv run pytest`" in description
    else:
        assert "- Commands:" not in description
