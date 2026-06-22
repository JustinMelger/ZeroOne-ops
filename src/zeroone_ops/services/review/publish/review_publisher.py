"""Review publisher."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from zeroone_ops.models.review import (
    ChangeRequestReviewContext,
    PriorReviewInlineComment,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    ReviewComment,
    ReviewFileContext,
)
from zeroone_ops.models.state import ReviewInlineCommentDecision
from zeroone_ops.providers.review.platform import (
    ChangeRequestReviewPublishClientProtocol,
    ReviewPlatformClientError,
)
from zeroone_ops.services.review.publish.review_response_state import (
    render_confidence_label,
    render_continuity_line,
    render_risk,
    render_summary_sentence,
    render_verdict,
    should_render_no_findings_detail,
)

_HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class ReviewPublishResult:
    """Capture the outcome of publishing a review note."""

    note: ReviewComment | None
    body: str
    artifact: PublishableReviewArtifact
    inline_comment_decisions: list[ReviewInlineCommentDecision] | None = None
    warning_message: str | None = None
    error_message: str | None = None


class ReviewPublisher:
    """Render and publish deterministic change-request review notes."""

    def __init__(self, review_client: ChangeRequestReviewPublishClientProtocol) -> None:
        """Initialize the review publisher."""
        self.review_client = review_client

    def publish_artifact(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        context: ChangeRequestReviewContext,
        artifact: PublishableReviewArtifact,
        inline_comment_decisions: list[ReviewInlineCommentDecision] | None = None,
    ) -> ReviewPublishResult:
        """Publish one note from a publish-shaped review artifact."""
        body = self.render_artifact(
            context=context,
            artifact=artifact,
        )
        try:
            note = self.review_client.create_change_request_comment(
                repository_id=repository_id,
                change_request_number=change_request_number,
                body=body,
            )
        except ReviewPlatformClientError as error:
            return ReviewPublishResult(
                note=None,
                body=body,
                artifact=artifact,
                inline_comment_decisions=inline_comment_decisions or [],
                error_message=f"Review note publish failed: {error}",
            )
        artifact_to_publish, updated_decisions = self._publish_inline_comments(
            repository_id=repository_id,
            change_request_number=change_request_number,
            context=context,
            artifact=artifact,
            inline_comment_decisions=inline_comment_decisions or [],
        )
        warning_messages: list[str] = []
        warning_messages.extend(_collect_inline_transport_warnings(updated_decisions))
        updated_decisions = [
            decision.model_copy(update={"authoritative_note_id": note.id})
            for decision in updated_decisions
        ]
        if artifact_to_publish != artifact:
            updated_body = self.render_artifact(
                context=context,
                artifact=artifact_to_publish,
            )
            try:
                note = self.review_client.update_change_request_comment(
                    repository_id=repository_id,
                    change_request_number=change_request_number,
                    note_id=note.id,
                    body=updated_body,
                )
                body = updated_body
            except ReviewPlatformClientError:
                warning_messages.append(
                    "Inline comments were published, but updating the authoritative review note "
                    "failed. Provider-backed continuity metadata for those inline comments is "
                    "incomplete, but local mirrored continuity was preserved."
                )
        return ReviewPublishResult(
            note=note,
            body=body,
            artifact=artifact_to_publish,
            inline_comment_decisions=updated_decisions,
            warning_message=(
                None if not warning_messages else " ".join(dict.fromkeys(warning_messages))
            ),
        )

    def _publish_inline_comments(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        context: ChangeRequestReviewContext,
        artifact: PublishableReviewArtifact,
        inline_comment_decisions: list[ReviewInlineCommentDecision],
    ) -> tuple[PublishableReviewArtifact, list[ReviewInlineCommentDecision]]:
        """Publish bounded inline comments before the authoritative summary note."""
        if not inline_comment_decisions or context.diff_refs is None:
            return artifact, inline_comment_decisions

        decision_by_key = {
            _decision_key(decision): decision for decision in inline_comment_decisions
        }
        updated_decisions: list[ReviewInlineCommentDecision] = []
        updated_findings: list[PublishableReviewFinding] = []
        for finding in artifact.findings:
            decision = decision_by_key.get(_finding_key(finding))
            if decision is None or decision.anchor_reuse_decision != "new":
                updated_findings.append(finding)
                if decision is not None:
                    updated_decisions.append(decision)
                continue

            position = _resolve_inline_position(context=context, finding=finding)
            if position is None:
                updated_findings.append(finding)
                updated_decisions.append(
                    decision.model_copy(
                        update={
                            "anchor_reuse_decision": "summary_only",
                            "anchor_reuse_reason": "inline_position_unavailable",
                        }
                    )
                )
                continue

            try:
                note = self.review_client.create_change_request_inline_comment(
                    repository_id=repository_id,
                    change_request_number=change_request_number,
                    body=_render_inline_comment_body(finding),
                    base_sha=context.diff_refs.base_sha,
                    start_sha=context.diff_refs.start_sha,
                    head_sha=context.diff_refs.head_sha,
                    old_path=position.old_path,
                    new_path=position.new_path,
                    new_line=position.new_line,
                )
            except ReviewPlatformClientError:
                updated_findings.append(finding)
                updated_decisions.append(
                    decision.model_copy(
                        update={
                            "anchor_reuse_decision": "summary_only",
                            "anchor_reuse_reason": "inline_publish_failed",
                        }
                    )
                )
                continue

            inline_comment = PriorReviewInlineComment(
                comment_id=str(note.id),
                comment_url=note.web_url,
                status="published",
                anchor_file_path=finding.file_path,
                anchor_line_start=finding.line_start,
                anchor_line_end=finding.line_end,
            )
            updated_findings.append(finding.model_copy(update={"inline_comment": inline_comment}))
            updated_decisions.append(decision.model_copy(update={"new_comment_id": str(note.id)}))

        if updated_findings == artifact.findings:
            return artifact, updated_decisions or inline_comment_decisions
        return (
            artifact.model_copy(update={"findings": updated_findings}),
            updated_decisions or inline_comment_decisions,
        )

    def render_artifact(
        self,
        *,
        context: ChangeRequestReviewContext,
        artifact: PublishableReviewArtifact,
    ) -> str:
        """Render one deterministic review note body from a publish-shaped artifact."""
        lines: list[str] = [f"**Verdict:** {render_verdict(artifact)}"]
        if artifact.classification == "findings_present":
            lines.append(f"**Risk:** {render_risk(artifact)}")
        lines.append(f"**Confidence:** {render_confidence_label(artifact)}")
        continuity_line = (
            None
            if artifact.classification == "manual_review_only"
            else render_continuity_line(artifact)
        )
        if continuity_line is not None:
            lines.append(continuity_line)
        lines.extend(["", render_summary_sentence(context=context, artifact=artifact)])

        if artifact.classification == "manual_review_only":
            lines.extend(
                [
                    artifact.summary,
                    "A human review is still needed before treating these changes as safe.",
                    *_render_advisory_notes(artifact),
                ]
            )
        elif artifact.classification == "findings_present":
            lines.extend(
                [
                    *_render_advisory_notes(artifact),
                    "",
                    "**Findings**",
                    *_render_findings(artifact.findings),
                ]
            )
        else:
            lines.extend(
                [
                    *_render_clear_detail(context=context, artifact=artifact),
                    *_render_advisory_notes(artifact),
                ]
            )

        lines.extend(
            [
                "",
                *_render_machine_safe_block(context=context, artifact=artifact),
            ]
        )
        return "\n".join(lines)


def _render_advisory_notes(artifact: PublishableReviewArtifact) -> list[str]:
    """Render repository-guidance-backed style observations when present."""
    if not artifact.advisory_notes:
        return []
    return [
        "",
        "Style Observations (Repository Guidance):",
        *[f"- {note}" for note in artifact.advisory_notes],
    ]


def _render_clear_detail(
    *,
    context: ChangeRequestReviewContext,
    artifact: PublishableReviewArtifact,
) -> list[str]:
    """Render one short follow-up clear detail when the summary adds context."""
    if not should_render_no_findings_detail(context=context, artifact=artifact):
        return []
    detail = _render_clear_detail_sentence(context=context, summary=artifact.summary)
    if detail is None:
        return []
    return ["", detail]


def _render_findings(findings: list[PublishableReviewFinding]) -> list[str]:
    """Render compact developer-facing finding lines."""
    lines: list[str] = []
    for index, finding in enumerate(findings, start=1):
        if lines:
            lines.append("")
        lines.append(f"{index}. `{finding.file_path}`")
        lines.extend(_render_single_finding_body(finding))
    return lines


def _render_single_finding_body(finding: PublishableReviewFinding) -> list[str]:
    """Render one finding using issue, explanation, and bounded fix guidance."""
    issue_sentence = _ensure_terminal_punctuation(finding.title)
    body_lines = [f"   {issue_sentence}"]
    consequence = _render_consequence_sentence(finding)
    if consequence is not None:
        body_lines.append(f"   {consequence}")
    suggested_fix = _render_suggested_fix_line(finding)
    if suggested_fix is not None:
        body_lines.append("")
        body_lines.append(f"   {suggested_fix}")
    return body_lines


def _render_consequence_sentence(finding: PublishableReviewFinding) -> str | None:
    """Return a short consequence sentence only when the impact is not already obvious."""
    explanation = finding.explanation.strip()
    if not explanation:
        return None
    if not _should_include_consequence_sentence(finding):
        return None
    return _ensure_terminal_punctuation(explanation)


def _should_include_consequence_sentence(finding: PublishableReviewFinding) -> bool:
    """Decide whether a second short consequence sentence materially helps clarity."""
    title = finding.title.lower()
    explanation = finding.explanation.lower()
    if explanation.startswith(title):
        return False
    return True


def _render_suggested_fix_line(finding: PublishableReviewFinding) -> str | None:
    """Render one short suggested-fix line when the follow-up text is present."""
    suggested_follow_up = finding.suggested_follow_up.strip()
    if not suggested_follow_up:
        return None
    return f"Suggested fix: {_ensure_terminal_punctuation(suggested_follow_up)}"


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


@dataclass(frozen=True)
class _InlinePosition:
    old_path: str
    new_path: str
    new_line: int


def _resolve_inline_position(
    *,
    context: ChangeRequestReviewContext,
    finding: PublishableReviewFinding,
) -> _InlinePosition | None:
    """Resolve one GitLab inline discussion position from review context."""
    if finding.line_start is None:
        return None
    changed_file = next(
        (item for item in context.changed_files if item.file_path == finding.file_path),
        None,
    )
    if changed_file is None:
        return None
    old_path = changed_file.old_path or changed_file.file_path
    new_path = changed_file.new_path or changed_file.file_path
    new_line = _best_inline_line(changed_file=changed_file, finding=finding)
    return _InlinePosition(old_path=old_path, new_path=new_path, new_line=new_line)


def _best_inline_line(
    *,
    changed_file: ReviewFileContext,
    finding: PublishableReviewFinding,
) -> int:
    """Pick the most specific changed line within the finding range when possible."""
    if finding.line_start is None:
        raise ValueError("Inline positions require finding.line_start.")
    if finding.line_end is None:
        return finding.line_start

    finding_start = finding.line_start
    finding_end = finding.line_end
    if changed_file.diff is None:
        return finding.line_start
    overlapping_hunks = [
        hunk_range
        for hunk_range in _changed_hunk_ranges(changed_file.diff)
        if not (finding_end < hunk_range[0] or finding_start > hunk_range[1])
    ]
    if not overlapping_hunks:
        return finding.line_start

    latest_changed_line = max(
        min(finding_end, hunk_end) for _hunk_start, hunk_end in overlapping_hunks
    )
    return latest_changed_line


def _changed_hunk_ranges(diff_text: str) -> list[tuple[int, int]]:
    """Extract new-side changed hunk ranges from one unified diff."""
    hunk_ranges: list[tuple[int, int]] = []
    for line in diff_text.splitlines():
        match = _HUNK_HEADER_PATTERN.match(line)
        if match is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or "1")
        end = start if count <= 0 else start + count - 1
        hunk_ranges.append((start, end))
    return hunk_ranges


def _render_inline_comment_body(finding: PublishableReviewFinding) -> str:
    """Render one short inline comment body."""
    return _ensure_terminal_punctuation(finding.title)


def _render_clear_detail_sentence(
    *,
    context: ChangeRequestReviewContext,
    summary: str,
) -> str | None:
    """Return one short clear-detail sentence when the summary is informative."""
    normalized = _normalize_summary(summary)
    if not normalized or normalized in _GENERIC_NO_FINDINGS_SUMMARIES:
        return None
    if _looks_like_prior_concern_resolution(normalized) and not _can_reference_prior_concern(
        context=context
    ):
        return None
    return _ensure_terminal_punctuation(summary)


def _normalize_summary(summary: str) -> str:
    """Normalize one summary string for generic-summary comparison."""
    return re.sub(r"\s+", " ", summary.strip().lower().rstrip(".!?"))


_GENERIC_NO_FINDINGS_SUMMARIES = {
    "no actionable findings",
    "no actionable findings in this pass",
    "no actionable findings in this review pass",
    "no actionable concerns in these changes",
}


def _looks_like_prior_concern_resolution(normalized_summary: str) -> bool:
    """Return whether the summary claims that an earlier concern was resolved."""
    return "earlier concern" in normalized_summary or "previous review" in normalized_summary


def _can_reference_prior_concern(*, context: ChangeRequestReviewContext) -> bool:
    """Return whether the latest prior pass supports concern-resolution wording."""
    prior_context = context.prior_review_context
    if prior_context is None or not prior_context.passes:
        return False
    return prior_context.passes[0].classification in {"findings_present", "manual_review_only"}


def _ensure_terminal_punctuation(text: str) -> str:
    """Ensure one short rendered sentence ends with terminal punctuation."""
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped[-1] in ".!?":
        return stripped
    return f"{stripped}."


def _finding_key(finding: PublishableReviewFinding) -> tuple[str | None, str, int | None, str]:
    """Build one stable lookup key for a publish finding."""
    return (
        finding.stable_identity,
        finding.file_path,
        finding.line_start,
        finding.region_hint or "",
    )


def _decision_key(
    decision: ReviewInlineCommentDecision,
) -> tuple[str | None, str, int | None, str]:
    """Build one stable lookup key for an inline-comment decision."""
    return (
        decision.finding_identity,
        decision.file_path,
        decision.line_start,
        decision.region_hint or "",
    )


def _render_machine_safe_block(
    *,
    context: ChangeRequestReviewContext,
    artifact: PublishableReviewArtifact,
) -> list[str]:
    """Render one bounded machine-safe note block for later MR reconstruction."""
    payload = {
        "schema": "ai-sonar-bot/review-note/v1",
        "reviewed_change_request_number": context.change_request_number,
        "reviewed_head_sha": context.head_sha,
        "classification": artifact.classification,
        "summary": artifact.summary,
        "findings_count": len(artifact.findings),
        "findings": [
            {
                "identity": finding.stable_identity,
                "legacy_identity": finding.legacy_identity,
                "summary": f"{finding.file_path}: {finding.title}",
                "severity": finding.severity,
                "file_path": finding.file_path,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
                "title": finding.title,
                "symbol": finding.symbol,
                "issue_kind": finding.issue_kind,
                "region_hint": finding.region_hint,
                "inline_comment": (
                    None
                    if finding.inline_comment is None
                    else {
                        "comment_id": finding.inline_comment.comment_id,
                        "comment_url": finding.inline_comment.comment_url,
                        "status": finding.inline_comment.status,
                        "anchor_file_path": finding.inline_comment.anchor_file_path,
                        "anchor_line_start": finding.inline_comment.anchor_line_start,
                        "anchor_line_end": finding.inline_comment.anchor_line_end,
                    }
                ),
            }
            for finding in artifact.findings
        ],
    }
    return [
        "<!-- ai-sonar-bot:review-note:v1",
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        "-->",
    ]


def _collect_inline_transport_warnings(
    decisions: list[ReviewInlineCommentDecision],
) -> list[str]:
    """Return operator-visible warnings for inline-comment transport failures."""
    warnings: list[str] = []
    failed_publish_count = sum(
        1 for decision in decisions if decision.anchor_reuse_reason == "inline_publish_failed"
    )
    if failed_publish_count:
        warnings.append(
            "One or more inline comments could not be published to GitLab. "
            f"Failed inline comments: {failed_publish_count}."
        )
    return warnings
