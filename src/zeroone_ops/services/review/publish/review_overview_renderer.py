"""Present completed review meaning separately from execution and CI evidence."""

from __future__ import annotations

import html
from urllib.parse import quote, urlsplit

from zeroone_ops.models.review_overview import ReviewOverviewEnvelope
from zeroone_ops.services.control_plane.review_projection import (
    review_feedback_projection_decision_service as feedback_projection,
)
from zeroone_ops.services.review.publish.review_overview_codec import (
    encode_overview,
    validate_overview_payload,
)
from zeroone_ops.services.review.publish.review_response_state import (
    render_confidence_label,
    render_risk,
    render_verdict,
)


def escape_overview_text(value: str) -> str:
    """Escape external prose without changing the stored accepted artifact."""
    escaped = html.escape(value, quote=True)
    for character in ("\\", "`", "*", "_", "[", "]", "|", "#"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


def _link(label: str, url: str | None) -> str:
    if url is None or urlsplit(url).scheme not in {"https", "http"}:
        return escape_overview_text(label)
    return f"[{escape_overview_text(label)}]({quote(url, safe=':/?=&%#')})"


def render_overview(envelope: ReviewOverviewEnvelope) -> str:
    """Render bounded history and complete serialized authority, never truncating it."""
    current = envelope.complete_passes[0]
    artifact = current.artifact
    lines = [
        "## Review Overview",
        "",
        f"**Reviewed commit:** `{escape_overview_text(current.head_sha)}`",
        f"**Comparison base:** `{escape_overview_text(current.diff_refs.base_sha)}`"
        if current.diff_refs is not None
        else "**Comparison base:** unavailable",
        f"**AI verdict:** {render_verdict(artifact)} | "
        f"**Risk:** {render_risk(artifact)} | "
        f"**Confidence:** {render_confidence_label(artifact)}",
        "",
        escape_overview_text(artifact.summary),
    ]
    if envelope.execution_notice is not None:
        lines.extend(["", "### Latest Execution", escape_overview_text(envelope.execution_notice)])
    if current.workflow_url:
        lines.extend(["", _link("Review workflow", current.workflow_url)])
    new_count = sum(finding.continuity_status == "new" for finding in artifact.findings)
    unresolved_count = sum(
        finding.continuity_status == "unresolved" for finding in artifact.findings
    )
    continuity_count = new_count + unresolved_count
    counts = f"**Active findings:** {len(artifact.findings)}"
    if continuity_count:
        counts += f" ({new_count} new, {unresolved_count} unresolved"
        unknown_count = len(artifact.findings) - continuity_count
        if unknown_count:
            counts += f", {unknown_count} without continuity classification"
        counts += ")"
    lines.extend(
        [
            "",
            counts,
            *[escape_overview_text(line) for line in artifact.follow_up_lines],
        ]
    )
    for index, finding in enumerate(artifact.findings, start=1):
        location = finding.file_path
        if finding.line_start is not None:
            location += f":{finding.line_start}"
        title = f"{finding.title} ({location})"
        inline_url = None if finding.inline_comment is None else finding.inline_comment.comment_url
        lines.extend(["", f"{index}. {_link(title, inline_url)}"])
        if inline_url is not None:
            lines.append(f"   Impact: {escape_overview_text(finding.explanation)}")
        else:
            lines.extend(
                [
                    f"   Evidence: {escape_overview_text(finding.evidence)}",
                    f"   Impact: {escape_overview_text(finding.explanation)}",
                    f"   Suggested follow-up: {escape_overview_text(finding.suggested_follow_up)}",
                ]
            )
    if artifact.advisory_notes:
        lines.extend(
            ["", "### Repository Guidance", *map(escape_overview_text, artifact.advisory_notes)]
        )
    next_action = {
        "findings_present": "Address the active findings and rerun review.",
        "manual_review_only": "Review these changes manually; automated review is inconclusive.",
        "no_findings": "Check independent validation and human review before merging.",
    }[artifact.classification]
    if (
        current.verified_work_item_url
        and urlsplit(current.verified_work_item_url).scheme in {"http", "https"}
        and feedback_projection.build_projected_review_feedback(artifact) is not None
    ):
        next_action += (
            " To request a revision, post `/zeroone remediation requeue` on the "
            f"{_link('work-item issue', current.verified_work_item_url)}, "
            "not on this change request."
        )
    lines.extend(
        [
            "",
            f"**Next action:** {next_action}",
            "",
            "<details>",
            "<summary>Recent review history</summary>",
            "",
        ]
    )
    complete_ids = {snapshot.pass_id for snapshot in envelope.complete_passes}
    for summary in envelope.history:
        availability = "" if summary.pass_id in complete_ids else " (summary only)"
        lines.append(
            f"- Pass {summary.sequence}: `{escape_overview_text(summary.head_sha)}` - "
            f"{summary.classification}, {summary.findings_count} findings; "
            f"{_link(summary.run_id, summary.workflow_url)}{availability}"
        )
    lines.extend(
        [
            "",
            "History is bounded to five summaries and two complete reviews; "
            "not a full audit archive.",
            "",
            "</details>",
            "",
            "AI review does not replace CI checks or merge approval.",
            "",
            encode_overview(envelope),
        ]
    )
    return validate_overview_payload("\n".join(lines))
