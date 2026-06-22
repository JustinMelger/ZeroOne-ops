"""Review response-state and summary rendering helpers."""

from __future__ import annotations

import re
from typing import Literal

from zeroone_ops.models.review import (
    ChangeRequestReviewContext,
    PriorReviewPass,
    PublishableReviewArtifact,
)


def render_summary_sentence(
    *,
    context: ChangeRequestReviewContext,
    artifact: PublishableReviewArtifact,
) -> str:
    """Render the short human-facing summary sentence."""
    prior_pass = _latest_prior_pass(context)
    if artifact.classification == "no_findings":
        if prior_pass is not None or _has_follow_up_context(artifact.follow_up_lines):
            return (
                "I took another look, and I don't see any actionable concerns in these changes now."
            )
        return "I don't see any actionable concerns in these changes."
    if artifact.classification == "manual_review_only":
        if prior_pass is not None:
            return _render_follow_up_manual_review_summary(prior_pass)
        if _has_follow_up_context(artifact.follow_up_lines):
            return (
                "I took another look, but I couldn't review these changes "
                "confidently enough to call them clear this time."
            )
        return "I couldn't review these changes confidently enough to call them clear."
    if prior_pass is not None:
        return _render_follow_up_summary_sentence(prior_pass=prior_pass, artifact=artifact)
    if _has_follow_up_context(artifact.follow_up_lines):
        return _render_fallback_follow_up_summary_sentence(artifact)
    findings_count = len(artifact.findings)
    if render_risk(artifact) == "High":
        concern_label = "concern" if findings_count == 1 else "concerns"
        return f"I'd block this because of {findings_count} actionable {concern_label}."
    if findings_count == 1:
        return "I noticed one actionable concern in these changes."
    return f"I noticed {findings_count} actionable concerns in these changes."


def render_verdict(
    artifact: PublishableReviewArtifact,
) -> Literal["Block", "Concern", "Clear", "Needs review"]:
    """Render the top-block verdict label."""
    if artifact.classification == "no_findings":
        return "Clear"
    if artifact.classification == "manual_review_only":
        return "Needs review"
    if render_risk(artifact) == "High":
        return "Block"
    return "Concern"


def render_risk(artifact: PublishableReviewArtifact) -> Literal["High", "Medium", "Low"]:
    """Render the top-block risk label."""
    if artifact.classification == "no_findings":
        return "Low"
    if artifact.classification == "manual_review_only":
        return "Medium"

    severity_order: dict[str, Literal["High", "Medium", "Low"]] = {
        "high": "High",
        "medium": "Medium",
        "low": "Low",
    }
    severities = [severity_order[finding.severity] for finding in artifact.findings]
    if "High" in severities:
        return "High"
    if "Medium" in severities:
        return "Medium"
    return "Low"


def render_confidence_label(
    artifact: PublishableReviewArtifact,
) -> Literal["High", "Medium", "Low"]:
    """Compress numeric confidence into the human-facing label."""
    if artifact.review_confidence is None:
        return "Medium"
    if artifact.review_confidence >= 0.8:
        return "High"
    if artifact.review_confidence >= 0.5:
        return "Medium"
    return "Low"


def render_continuity_line(artifact: PublishableReviewArtifact) -> str | None:
    """Render one compact continuity line only when prior-review context adds value."""
    summary = _summarize_follow_up_lines(artifact.follow_up_lines)
    if summary is None:
        return None
    return f"**Continuity:** {summary}"


def should_render_no_findings_detail(
    *,
    context: ChangeRequestReviewContext,
    artifact: PublishableReviewArtifact,
) -> bool:
    """Return whether a clear note may show one extra summary-detail sentence."""
    if artifact.classification != "no_findings":
        return False
    del context
    return True


def _has_follow_up_context(lines: list[str]) -> bool:
    """Return whether the note has meaningful follow-up context from an earlier pass."""
    return any(line.strip() for line in lines)


def _latest_prior_pass(context: ChangeRequestReviewContext) -> PriorReviewPass | None:
    """Return the latest bounded prior pass when available."""
    prior_context = context.prior_review_context
    if prior_context is None or not prior_context.passes:
        return None
    return prior_context.passes[0]


def _prior_pass_was_blocking(prior_pass: PriorReviewPass) -> bool:
    """Return whether the prior pass likely represented a blocking concern."""
    return any((finding.severity or "").lower() == "high" for finding in prior_pass.findings)


def _render_follow_up_manual_review_summary(prior_pass: PriorReviewPass) -> str:
    """Render one follow-up summary sentence for a manual-review-only pass."""
    if prior_pass.classification == "no_findings":
        return (
            "I took another look, but I couldn't review these changes confidently "
            "enough to call them clear this time."
        )
    if prior_pass.classification == "manual_review_only":
        return (
            "I took another look, but I still couldn't review these changes "
            "confidently enough to call them clear."
        )
    if _prior_pass_was_blocking(prior_pass):
        return (
            "I took another look, but I couldn't review these changes confidently "
            "enough to confirm the earlier blocking concern this time."
        )
    return (
        "I took another look, but I couldn't review these changes confidently "
        "enough to confirm the earlier concern this time."
    )


def _render_follow_up_summary_sentence(
    *,
    prior_pass: PriorReviewPass,
    artifact: PublishableReviewArtifact,
) -> str:
    """Render a conversational summary sentence for follow-up passes with findings."""
    findings_count = len(artifact.findings)
    concern_label = "concern" if findings_count == 1 else "concerns"
    current_is_block = render_risk(artifact) == "High"
    prior_classification = prior_pass.classification

    if current_is_block:
        if prior_classification == "findings_present" and _prior_pass_was_blocking(prior_pass):
            return (
                "I took another look, and I'd still block this because of "
                f"{findings_count} actionable {concern_label}."
            )
        if prior_classification == "manual_review_only":
            return (
                "I took another look, and I'd now block this because of "
                f"{findings_count} actionable {concern_label}."
            )
        return (
            "I took another look, and I'd block this now because of "
            f"{findings_count} actionable {concern_label}."
        )

    if prior_classification == "manual_review_only":
        if findings_count == 1:
            return "I took another look, and I now notice one actionable concern in these changes."
        return (
            "I took another look, and I now notice "
            f"{findings_count} actionable concerns in these changes."
        )
    if prior_classification == "findings_present":
        if findings_count == 1:
            return (
                "I took another look, and I still notice one actionable concern in these changes."
            )
        return (
            "I took another look, and I still notice "
            f"{findings_count} actionable concerns in these changes."
        )
    if prior_classification == "no_findings":
        if findings_count == 1:
            return "I took another look, and I noticed one actionable concern in these changes now."
        return (
            "I took another look, and I noticed "
            f"{findings_count} actionable concerns in these changes now."
        )
    return _render_fallback_follow_up_summary_sentence(artifact)


def _render_fallback_follow_up_summary_sentence(artifact: PublishableReviewArtifact) -> str:
    """Render one bounded fallback follow-up summary when prior state is unavailable."""
    findings_count = len(artifact.findings)
    concern_label = "concern" if findings_count == 1 else "concerns"
    continuity_summary = _summarize_follow_up_lines(artifact.follow_up_lines) or ""
    if "new" in continuity_summary:
        if render_risk(artifact) == "High":
            return (
                "I took another look, and I'd block this now because of "
                f"{findings_count} actionable {concern_label}."
            )
        if findings_count == 1:
            return "I took another look, and I noticed one actionable concern in these changes now."
        return (
            "I took another look, and I noticed "
            f"{findings_count} actionable concerns in these changes now."
        )
    if "repeated" in continuity_summary:
        if render_risk(artifact) == "High":
            return (
                "I took another look, and I'd still block this because of "
                f"{findings_count} actionable {concern_label}."
            )
        if findings_count == 1:
            return (
                "I took another look, and I still notice one actionable concern in these changes."
            )
        return (
            "I took another look, and I still notice "
            f"{findings_count} actionable concerns in these changes."
        )
    if render_risk(artifact) == "High":
        return (
            "I took another look, and I'd block this because of "
            f"{findings_count} actionable {concern_label}."
        )
    if findings_count == 1:
        return "I took another look, and I noticed one actionable concern in these changes."
    return (
        f"I took another look, and I noticed {findings_count} actionable concerns in these changes."
    )


def _summarize_follow_up_lines(lines: list[str]) -> str | None:
    """Compress existing follow-up wording into a compact continuity label."""
    if not lines:
        return None

    unresolved_count = 0
    new_count = 0
    resolved_count = 0
    ambiguous = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("Follow-up review after"):
            continue
        lower = line.lower()
        if "still appears unresolved" in lower:
            unresolved_count += _extract_count_from_overlap_line(
                line=line,
                singular_prefix="An earlier concern",
                plural_phrase="earlier concerns",
            )
        if "no longer appears present" in lower:
            resolved_count += _extract_count_from_overlap_line(
                line=line,
                singular_prefix="One earlier concern",
                plural_phrase="earlier concerns",
            )
        new_count += _extract_new_concern_count(line)
        if "overlap is not fully clear" in lower:
            ambiguous = True
        if "not confident enough to verify continuity fully" in lower:
            ambiguous = True

    parts: list[str] = []
    if unresolved_count:
        parts.append(_counted_status(unresolved_count, "repeated"))
    if new_count:
        parts.append(_counted_status(new_count, "new"))
    if resolved_count:
        parts.append(_counted_status(resolved_count, "resolved"))
    if ambiguous:
        parts.append("overlap unclear")
    if not parts:
        return None
    return ", ".join(parts)


def _extract_count_from_overlap_line(
    *,
    line: str,
    singular_prefix: str,
    plural_phrase: str,
) -> int:
    """Extract one overlap count from normalized follow-up wording."""
    if line.startswith(singular_prefix):
        return 1
    match = re.search(r"(\d+)\s+" + re.escape(plural_phrase), line)
    if match is None:
        return 0
    return int(match.group(1))


def _extract_new_concern_count(line: str) -> int:
    """Extract how many new concerns the overlap summary reports."""
    if "introduces a new concern" in line:
        return 1
    match = re.search(r"introduces (\d+) new concerns", line)
    if match is None:
        return 0
    return int(match.group(1))


def _counted_status(count: int, label: str) -> str:
    """Render one counted continuity status phrase."""
    if count == 1:
        return f"1 {label}"
    return f"{count} {label}"
