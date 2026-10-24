"""Render bounded batch rejection evidence without granting it authority."""

import html

from zeroone_ops.models.batch_execution import BatchAnalysisRejection


def render_batch_analysis_rejection_lines(rejection: BatchAnalysisRejection) -> list[str]:
    """Return the shared operator explanation for an all-or-nothing analysis stop."""
    lines = [
        "",
        "### Batch Analysis Rejection",
        "",
        f"- Reason: `{rejection.reason}`",
        "- No partial edit was generated. Correct the cause before requeueing.",
        *[
            f"- Member: {_literal_text(member.finding_reference)}. "
            f"Reason: {_literal_text(member.reason)}"
            for member in rejection.members
        ],
    ]
    if rejection.omitted_member_count:
        lines.append(f"- ... and {rejection.omitted_member_count} more members.")
    return lines


def _literal_text(value: str) -> str:
    """Keep model-provided references and reasons on a literal Markdown line."""
    escaped = html.escape(" ".join(value.splitlines()), quote=False)
    for character in "\\`*_[]":
        escaped = escaped.replace(character, "\\" + character)
    return escaped
