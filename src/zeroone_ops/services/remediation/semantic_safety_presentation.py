"""Present internal semantic-safety evidence as an operator-facing change rationale."""

from __future__ import annotations

from zeroone_ops.models.analysis import SemanticSafetyAssessment
from zeroone_ops.models.work_item import WorkItemSemanticSafety


def render_semantic_safety_lines(
    semantic_safety: WorkItemSemanticSafety | SemanticSafetyAssessment,
) -> list[str]:
    """Return deterministic Markdown lines without exposing raw execution evidence."""
    return _render_rationale_lines(semantic_safety, "Change Rationale")


def render_retained_change_rationale_lines(semantic_safety: WorkItemSemanticSafety) -> list[str]:
    """Identify earlier rationale without inventing a run or publication association."""
    return _render_rationale_lines(
        semantic_safety,
        "Retained Change Rationale",
        "Retained from earlier analysis; not produced by this failed attempt.",
    )


def _render_rationale_lines(
    semantic_safety: WorkItemSemanticSafety | SemanticSafetyAssessment,
    heading: str,
    context_note: str | None = None,
) -> list[str]:
    """Share escaping and assessment presentation across current and retained evidence."""
    if isinstance(semantic_safety, WorkItemSemanticSafety):
        assessment = semantic_safety.assessment
        rejection_reason = semantic_safety.rejection_reason
    else:
        assessment = semantic_safety
        rejection_reason = None

    if assessment is None and rejection_reason is None:
        return []

    lines = ["", f"## {heading}", ""]
    if context_note is not None:
        lines.extend([context_note, ""])
    if rejection_reason is not None:
        lines.extend([f"- Why remediation stopped: {_escape_markdown_text(rejection_reason)}", ""])
    if assessment is None:
        lines.append("No change rationale was available.")
        return lines
    lines.extend(
        [
            "Model-provided explanation; not independent verification. "
            "See validation and review results.",
            "",
            f"- Current behavior: {_escape_markdown_text(assessment.current_behavior)}",
            f"- Intended change: {_escape_markdown_text(assessment.intended_behavior)}",
            "- Why existing behavior should be preserved:",
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
