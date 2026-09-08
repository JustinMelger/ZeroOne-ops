"""Render bounded semantic-safety evidence for operator-facing Markdown."""

from __future__ import annotations

from zeroone_ops.models.analysis import SemanticSafetyAssessment
from zeroone_ops.models.work_item import WorkItemSemanticSafety


def render_semantic_safety_lines(
    semantic_safety: WorkItemSemanticSafety | SemanticSafetyAssessment,
) -> list[str]:
    """Return deterministic Markdown lines without exposing raw execution evidence."""
    if isinstance(semantic_safety, WorkItemSemanticSafety):
        assessment = semantic_safety.assessment
        rejection_reason = semantic_safety.rejection_reason
    else:
        assessment = semantic_safety
        rejection_reason = None

    lines = ["", "## Semantic Safety", ""]
    if rejection_reason is not None:
        lines.append(f"- Decision: {_escape_markdown_text(rejection_reason)}")
    if assessment is None:
        lines.append("No semantic-safety assessment was available.")
        return lines
    lines.extend(
        [
            f"- Current behavior: {_escape_markdown_text(assessment.current_behavior)}",
            f"- Intended behavior: {_escape_markdown_text(assessment.intended_behavior)}",
            "- Preservation evidence:",
            *[
                f"  - {_escape_markdown_text(evidence)}"
                for evidence in assessment.preservation_evidence
            ],
        ]
    )
    return lines


def _escape_markdown_text(value: str) -> str:
    """Render model-provided text as one literal Markdown line."""
    escaped = value.replace("\\", "\\\\").replace("\r", " ").replace("\n", " ")
    escaped = escaped.replace("*", "\\*").replace("_", "\\_")
    escaped = escaped.replace("[", "\\[").replace("]", "\\]")
    return escaped.replace("<", "&lt;").replace(">", "&gt;")
