"""Render bounded batch rejection evidence without granting it authority."""

import html

from zeroone_ops.models.batch_execution import (
    BatchAnalysisRejection,
    BatchAnalysisRejectionView,
    BatchAttemptEvidence,
    BatchRejectedMemberView,
)

_STOP_OUTCOME = "No edit was generated or published by this attempt."


def build_batch_analysis_rejection_view(
    rejection: BatchAnalysisRejection,
    *,
    attempt: BatchAttemptEvidence | None = None,
    file_path: str | None = None,
    rule_id: str | None = None,
) -> BatchAnalysisRejectionView:
    """Resolve only exact, unambiguous recorded locations; never infer truncated identities."""
    summaries = {
        "manual_classification": "Model requested manual handling.",
        "missing_coverage": "Model response did not account for the batch findings.",
        "invalid_coverage": "Model response contained inconsistent batch accounting.",
        "unaddressable_members": "Model could not address every targeted finding.",
    }
    return BatchAnalysisRejectionView(
        summary=summaries[rejection.reason],
        members=tuple(
            BatchRejectedMemberView(
                recorded_location=_recorded_location(
                    member.finding_reference, attempt, file_path, rule_id
                ),
                explanation=_display_text(member.reason, 600),
                finding_reference=member.finding_reference,
            )
            for member in rejection.members
        ),
        reason_code=rejection.reason,
        omitted_member_count=rejection.omitted_member_count,
    )


def format_batch_analysis_stop(view: BatchAnalysisRejectionView) -> str:
    """Build the same bounded plain-text explanation for new failure state and CI output."""
    lines = [f"Batch analysis stopped: {view.summary}", _STOP_OUTCOME]
    for member in view.members[:3]:
        lines.extend(
            [
                f"Recorded location: {member.recorded_location}",
                f"Explanation: {_display_text(member.explanation, 300)}",
            ]
        )
    omitted = view.omitted_member_count + max(0, len(view.members) - 3)
    if omitted:
        lines.append(f"... and {omitted} more affected findings; see the work-item issue.")
    return "\n".join(lines)


def render_batch_analysis_stop_lines(view: BatchAnalysisRejectionView) -> list[str]:
    """Render a compact current-failure notice with no raw technical identities."""
    lines = ["", "### Latest Attempt", "", _literal_text(view.summary), "", _STOP_OUTCOME]
    for member in view.members[:3]:
        lines.extend(
            [
                f"- Recorded location: {_literal_text(member.recorded_location)}",
                f"  - Explanation: {_literal_text(_display_text(member.explanation, 300))}",
            ]
        )
    omitted = view.omitted_member_count + max(0, len(view.members) - 3)
    if omitted:
        lines.append(f"- ... and {omitted} more affected findings; see Last Execution.")
    return lines


def render_batch_analysis_rejection_lines(view: BatchAnalysisRejectionView) -> list[str]:
    """Return the shared operator explanation for an all-or-nothing analysis stop."""
    lines = [
        "",
        "### Batch Analysis Rejection",
        "",
        _literal_text(view.summary),
        _STOP_OUTCOME,
        *[
            f"- Recorded location: {_literal_text(member.recorded_location)}. "
            f"Explanation: {_literal_text(member.explanation)}"
            for member in view.members
        ],
    ]
    if view.omitted_member_count:
        lines.append(f"- ... and {view.omitted_member_count} more affected findings.")
    lines.extend(
        [
            "",
            "<details>",
            "<summary>Technical finding references</summary>",
            "",
            f"- Reason code: `{view.reason_code}`",
            *(f"- Member: {_literal_text(member.finding_reference)}" for member in view.members),
            "",
            "</details>",
        ]
    )
    return lines


def _recorded_location(
    reference: str, attempt: BatchAttemptEvidence | None, path: str | None, rule: str | None
) -> str:
    """Fall back to shared scope when the bounded reference cannot identify exactly one member."""
    matches = [m for m in attempt.members if m.finding_id == reference] if attempt else []
    truncated = len(reference) == 300 and reference.endswith("...")
    line = None
    if len(matches) == 1 and not truncated:
        member = matches[0]
        path, rule, line = (
            member.repository_path,
            member.remediation_context.diagnostic_code,
            member.line_start,
        )
    location = _display_text(path or "File unavailable", 300)
    location += f":{line}" if line is not None and line > 0 else " (line unavailable)"
    return f"{location}; rule: {_display_text(rule or 'unavailable', 300)}"


def _display_text(value: str, limit: int) -> str:
    """Flatten untrusted display text, remove terminal controls, and visibly bound excerpts."""
    flattened = " ".join(value.splitlines())
    printable = "".join(character for character in flattened if character.isprintable())
    return printable if len(printable) <= limit else printable[: limit - 3] + "..."


def _literal_text(value: str) -> str:
    """Keep model-provided references and reasons on a literal Markdown line."""
    escaped = html.escape(" ".join(value.splitlines()), quote=False)
    for character in "\\`*_[]":
        escaped = escaped.replace(character, "\\" + character)
    return escaped
