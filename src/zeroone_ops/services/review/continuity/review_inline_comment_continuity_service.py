"""Inline-comment continuity preparation for review publishing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from zeroone_ops.models.review import (
    ChangeRequestReviewContext,
    PriorReviewFinding,
    PriorReviewPass,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    ReviewFileContext,
)
from zeroone_ops.models.state import ReviewInlineCommentDecision

LocationTrust = Literal["trusted", "weak", "untrusted"]
AnchorReuseDecision = Literal["reuse", "new", "summary_only"]
_SUPPORTED_INLINE_SEVERITIES = frozenset({"high", "medium"})
_MAX_REUSABLE_LINE_DRIFT = 3
_HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_MIN_GROUNDING_TOKEN_LENGTH = 4


@dataclass(frozen=True)
class InlineCommentContinuityResult:
    """Capture inline-comment continuity preparation for one artifact."""

    artifact: PublishableReviewArtifact
    reused_inline_comment_count: int = 0
    decisions: list[ReviewInlineCommentDecision] = field(default_factory=list)


class ReviewInlineCommentContinuityService:
    """Prepare publish artifacts to reuse prior inline-comment continuity safely."""

    def apply_if_enabled(
        self,
        *,
        enabled: bool,
        context: ChangeRequestReviewContext,
        artifact: PublishableReviewArtifact,
    ) -> InlineCommentContinuityResult:
        """Apply inline-comment continuity only when the feature flag is enabled."""
        if not enabled:
            return InlineCommentContinuityResult(artifact=artifact)
        return self.apply(context=context, artifact=artifact)

    def apply(
        self,
        *,
        context: ChangeRequestReviewContext,
        artifact: PublishableReviewArtifact,
    ) -> InlineCommentContinuityResult:
        """Mirror reusable prior inline-comment metadata onto current findings."""
        if artifact.classification != "findings_present":
            return InlineCommentContinuityResult(artifact=artifact)

        latest_pass = _latest_prior_pass(context)
        prior_findings_by_identity = (
            {} if latest_pass is None else _relevant_prior_findings_by_identity(latest_pass)
        )

        reused_inline_comment_count = 0
        decisions: list[ReviewInlineCommentDecision] = []
        updated_findings: list[PublishableReviewFinding] = []
        for finding in artifact.findings:
            prior_finding = (
                None
                if finding.stable_identity is None
                else prior_findings_by_identity.get(finding.stable_identity)
            )
            location_trust = _location_trust(context=context, finding=finding)
            decision, reason = _decision_for_finding(
                finding=finding,
                prior_finding=prior_finding,
                location_trust=location_trust,
            )
            decisions.append(
                ReviewInlineCommentDecision(
                    finding_identity=finding.stable_identity,
                    severity=finding.severity,
                    file_path=finding.file_path,
                    line_start=finding.line_start,
                    line_end=finding.line_end,
                    region_hint=finding.region_hint,
                    inline_comments_enabled=True,
                    location_trust=location_trust,
                    existing_inline_comment_found=prior_finding is not None,
                    anchor_reuse_decision=decision,
                    anchor_reuse_reason=reason,
                    authoritative_note_id=None if latest_pass is None else latest_pass.note_id,
                    existing_comment_id=(
                        None
                        if prior_finding is None or prior_finding.inline_comment is None
                        else prior_finding.inline_comment.comment_id
                    ),
                    new_comment_id=None,
                )
            )

            if decision != "reuse" or prior_finding is None or prior_finding.inline_comment is None:
                updated_findings.append(finding)
                continue

            reused_inline_comment_count += 1
            updated_findings.append(
                finding.model_copy(update={"inline_comment": prior_finding.inline_comment})
            )

        if reused_inline_comment_count == 0:
            return InlineCommentContinuityResult(artifact=artifact, decisions=decisions)
        return InlineCommentContinuityResult(
            artifact=artifact.model_copy(update={"findings": updated_findings}),
            reused_inline_comment_count=reused_inline_comment_count,
            decisions=decisions,
        )


def _decision_for_finding(
    *,
    finding: PublishableReviewFinding,
    prior_finding: PriorReviewFinding | None,
    location_trust: LocationTrust,
) -> tuple[AnchorReuseDecision, str]:
    """Return the bounded inline-comment continuity decision for one finding."""
    if finding.inline_comment is not None:
        return ("summary_only", "current_inline_comment_already_present")
    if finding.stable_identity is None:
        return ("summary_only", "missing_stable_identity")
    if finding.severity not in _SUPPORTED_INLINE_SEVERITIES:
        return ("summary_only", "severity_not_supported")
    if location_trust == "untrusted":
        return ("summary_only", "location_untrusted")
    if location_trust == "weak":
        return ("summary_only", "location_weak")
    if prior_finding is None or prior_finding.inline_comment is None:
        return ("new", "trusted_new_anchor")
    if not _anchor_is_reusable(current_finding=finding, prior_finding=prior_finding):
        return ("summary_only", "prior_inline_comment_not_reopened")
    return ("reuse", "existing_anchor_reused")


def _latest_prior_pass(context: ChangeRequestReviewContext) -> PriorReviewPass | None:
    """Return the latest available prior review pass when present."""
    if context.prior_review_context is None or not context.prior_review_context.passes:
        return None
    return context.prior_review_context.passes[0]


def _relevant_prior_findings_by_identity(
    prior_pass: PriorReviewPass,
) -> dict[str, PriorReviewFinding]:
    """Index prior findings with relevant inline-comment metadata by canonical identity."""
    indexed_findings: dict[str, PriorReviewFinding] = {}
    for finding in prior_pass.findings:
        if finding.identity is None:
            continue
        if finding.inline_comment is None:
            continue
        if finding.inline_comment.status != "published":
            continue
        indexed_findings.setdefault(finding.identity, finding)
    return indexed_findings


def _location_trust(
    *,
    context: ChangeRequestReviewContext,
    finding: PublishableReviewFinding,
) -> LocationTrust:
    """Classify whether one finding anchor is trusted enough for inline reuse."""
    changed_file = next(
        (
            changed_file
            for changed_file in context.changed_files
            if changed_file.file_path == finding.file_path
        ),
        None,
    )
    if changed_file is None:
        return "untrusted"
    if finding.line_start is None or finding.line_end is None:
        return "untrusted"

    if finding.line_end < changed_file.start_line or finding.line_start > changed_file.end_line:
        return "weak"

    hunk_ranges = _changed_hunk_ranges(changed_file.diff)
    if not hunk_ranges:
        return "weak"

    candidate_range = (finding.line_start, finding.line_end)
    matching_hunk_ranges = [
        hunk_range
        for hunk_range in hunk_ranges
        if _ranges_overlap_or_drift(candidate_range, hunk_range)
    ]
    if not matching_hunk_ranges:
        return "weak"
    if len(matching_hunk_ranges) > 1:
        return "weak"
    if not _local_grounding_evidence_present(changed_file=changed_file, finding=finding):
        return "weak"
    return "trusted"


def _anchor_is_reusable(
    *,
    current_finding: PublishableReviewFinding,
    prior_finding: PriorReviewFinding,
) -> bool:
    """Return whether a prior inline anchor is still reusable for this finding."""
    prior_inline_comment = prior_finding.inline_comment
    if prior_inline_comment is None:
        return False
    if prior_inline_comment.anchor_file_path != current_finding.file_path:
        return False
    if not _same_local_region(current_finding=current_finding, prior_finding=prior_finding):
        return False
    if (
        current_finding.line_start is None
        or current_finding.line_end is None
        or prior_inline_comment.anchor_line_start is None
        or prior_inline_comment.anchor_line_end is None
    ):
        return False
    return _ranges_overlap_or_drift(
        (current_finding.line_start, current_finding.line_end),
        (prior_inline_comment.anchor_line_start, prior_inline_comment.anchor_line_end),
    )


def _same_local_region(
    *,
    current_finding: PublishableReviewFinding,
    prior_finding: PriorReviewFinding,
) -> bool:
    """Return whether current and prior findings describe the same local region."""
    if (
        current_finding.region_hint is not None
        and prior_finding.region_hint is not None
        and current_finding.region_hint == prior_finding.region_hint
    ):
        return True
    if (
        current_finding.symbol is not None
        and prior_finding.symbol is not None
        and current_finding.symbol == prior_finding.symbol
    ):
        return True
    return (
        current_finding.issue_kind is not None
        and prior_finding.issue_kind is not None
        and current_finding.issue_kind == prior_finding.issue_kind
        and current_finding.title == prior_finding.title
    )


def _ranges_overlap_or_drift(
    current_range: tuple[int, int],
    prior_range: tuple[int, int],
) -> bool:
    """Return whether two line ranges overlap or drift only slightly."""
    current_start, current_end = current_range
    prior_start, prior_end = prior_range
    if current_start <= prior_end and prior_start <= current_end:
        return True
    return (
        min(abs(current_start - prior_start), abs(current_end - prior_end))
        <= _MAX_REUSABLE_LINE_DRIFT
    )


def _changed_hunk_ranges(diff: str | None) -> list[tuple[int, int]]:
    """Parse changed hunk ranges from one unified diff."""
    if not diff:
        return []
    hunk_ranges: list[tuple[int, int]] = []
    for raw_line in diff.splitlines():
        match = _HUNK_HEADER_PATTERN.match(raw_line)
        if match is None:
            continue
        hunk_start = int(match.group(1))
        hunk_length = int(match.group(2) or "1")
        hunk_end = max(hunk_start, hunk_start + max(hunk_length - 1, 0))
        hunk_ranges.append((hunk_start, hunk_end))
    return hunk_ranges


def _local_grounding_evidence_present(
    *,
    changed_file: ReviewFileContext,
    finding: PublishableReviewFinding,
) -> bool:
    """Return whether the current file context shows bounded local grounding evidence."""
    local_text = _text_for_finding_lines(
        content=changed_file.content,
        line_start=finding.line_start,
        line_end=finding.line_end,
    )
    if not local_text:
        return False
    grounding_tokens = _grounding_tokens(finding)
    if not grounding_tokens:
        return False
    lowered_local_text = local_text.lower()
    return any(token in lowered_local_text for token in grounding_tokens)


def _text_for_finding_lines(*, content: str, line_start: int | None, line_end: int | None) -> str:
    """Extract the rendered local content that corresponds to the finding lines."""
    if line_start is None or line_end is None:
        return ""
    collected: list[str] = []
    for raw_line in content.splitlines():
        match = re.match(r"^\s*(\d+):\s?(.*)$", raw_line)
        if match is None:
            continue
        source_line = int(match.group(1))
        if line_start <= source_line <= line_end:
            collected.append(match.group(2))
    return "\n".join(collected)


def _grounding_tokens(finding: PublishableReviewFinding) -> set[str]:
    """Return bounded grounding tokens that should appear near a trusted anchor."""
    tokens: set[str] = set()
    for value in (
        finding.symbol,
        finding.region_hint,
        finding.issue_kind,
        finding.title,
        finding.evidence,
    ):
        if value is None:
            continue
        for token in re.findall(r"[a-z0-9_]+", value.lower()):
            if len(token) >= _MIN_GROUNDING_TOKEN_LENGTH:
                tokens.add(token)
    return tokens
