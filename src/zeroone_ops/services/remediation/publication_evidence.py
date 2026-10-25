"""Render and replace bot-owned publication evidence without claiming surrounding text."""

import html
import re

from zeroone_ops.models.analysis import (
    SemanticSafetyAssessment,
    ValidationComparison,
    ValidationResult,
)
from zeroone_ops.services.remediation.semantic_safety_presentation import (
    render_semantic_safety_lines,
)

EVIDENCE_START = "<!-- zeroone:publication-evidence:start -->"
EVIDENCE_END = "<!-- zeroone:publication-evidence:end -->"


def render_publication_evidence(
    *,
    validation_comparison: ValidationComparison | None = None,
    validation_result: ValidationResult | None = None,
    semantic_safety: SemanticSafetyAssessment | None = None,
    commit_sha: str | None = None,
) -> str:
    """Render evidence from execution results, never from publication success."""
    lines = [EVIDENCE_START]
    if commit_sha is not None:
        lines.extend(
            [
                "## Latest Revision Evidence",
                "",
                f"- Published commit: `{_literal_text(commit_sha)}`",
                "- Supersedes earlier validation and rationale in this description.",
                "",
            ]
        )
    result = validation_comparison.post_edit if validation_comparison else validation_result
    if validation_comparison is not None and validation_comparison.outcome == "baseline_preserved":
        status = "Validation baseline preserved"
    elif result is None:
        status = "Validation evidence unavailable"
    elif not result.passed or any(command.exit_code != 0 for command in result.results):
        status = "Validation failed"
    elif not result.results:
        status = "No validation commands configured"
    else:
        status = "Validation passed"
    lines.extend(["## Validation", f"- Status: {status}"])
    if result is not None and result.results:
        lines.append(
            "- Commands: " + ", ".join(_command_code(command.command) for command in result.results)
        )
    if semantic_safety is not None:
        lines.extend(render_semantic_safety_lines(semantic_safety))
    lines.extend(["", EVIDENCE_END])
    return "\n".join(lines)


def replace_publication_evidence(description: str, evidence: str) -> str:
    """Replace one complete owned block, or prepend evidence to untouched legacy text."""
    span = _owned_span(description)
    if _owned_span(evidence) != (0, len(evidence)):
        raise ValueError("Generated publication evidence must contain exactly one managed block.")
    if span is None:
        return evidence + "\n\n" + description
    start, end = span
    return description[:start] + evidence + description[end:]


def _owned_span(description: str) -> tuple[int, int] | None:
    """Reject ambiguous or damaged markers rather than guessing which text belongs to the bot."""
    markers = list(re.finditer(r"<!--\s*zeroone:publication-evidence", description, re.IGNORECASE))
    if not markers:
        return None
    if (
        len(markers) != 2
        or description.count(EVIDENCE_START) != 1
        or description.count(EVIDENCE_END) != 1
    ):
        raise ValueError("Publication evidence markers are incomplete or ambiguous.")
    start, end = description.index(EVIDENCE_START), description.index(EVIDENCE_END)
    if end <= start:
        raise ValueError("Publication evidence markers are out of order.")
    for position, marker in ((start, EVIDENCE_START), (end, EVIDENCE_END)):
        suffix = description[position + len(marker) :]
        if (position > 0 and description[position - 1] != "\n") or (
            suffix and not suffix.startswith(("\n", "\r\n"))
        ):
            raise ValueError("Publication evidence markers must occupy their own lines.")
    return start, end + len(EVIDENCE_END)


def _literal_text(value: str) -> str:
    """Keep command/SHA evidence literal and unable to terminate a managed block."""
    return html.escape(" ".join(value.splitlines()), quote=False).replace("`", "&#96;")


def _command_code(command: str) -> str:
    """HTML code preserves special characters visually without allowing raw ownership markers."""
    flattened = " ".join(command.splitlines())
    if any(character in flattened for character in "<&`"):
        return f"<code>{html.escape(flattened, quote=False)}</code>"
    return f"`{flattened}`"
