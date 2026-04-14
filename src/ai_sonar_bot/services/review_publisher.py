"""Review publisher."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ai_sonar_bot.models.gitlab import MergeRequestNote
from ai_sonar_bot.models.review import (
    MergeRequestReviewContext,
    ReviewFinding,
    ReviewResult,
)
from ai_sonar_bot.providers.gitlab_client import GitLabClientError
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient


@dataclass(frozen=True)
class ReviewPublishResult:
    """Capture the outcome of publishing a review note."""

    note: MergeRequestNote | None
    body: str
    error_message: str | None = None


@dataclass(frozen=True)
class FollowUpFindingStatus:
    """Represent one bounded follow-up comparison outcome."""

    summary: str
    file_path: str | None
    status: str


@dataclass(frozen=True)
class FollowUpReviewReconciliation:
    """Represent a conservative comparison against the latest prior pass."""

    prior_reviewed_head_sha: str
    still_unresolved: list[FollowUpFindingStatus] = field(default_factory=list)
    appears_resolved: list[FollowUpFindingStatus] = field(default_factory=list)
    new_findings: list[FollowUpFindingStatus] = field(default_factory=list)


class ReviewPublisher:
    """Render and publish deterministic merge-request review notes."""

    def __init__(self, review_client: GitLabReviewClient) -> None:
        """Initialize the review publisher."""
        self.review_client = review_client

    def publish(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        context: MergeRequestReviewContext,
        review_result: ReviewResult,
    ) -> ReviewPublishResult:
        """Publish one deterministic review summary note."""
        body = self.render_note(context=context, review_result=review_result)
        try:
            note = self.review_client.create_merge_request_note(
                project_id=project_id,
                merge_request_iid=merge_request_iid,
                body=body,
            )
        except GitLabClientError as error:
            return ReviewPublishResult(
                note=None,
                body=body,
                error_message=f"Review note publish failed: {error}",
            )
        return ReviewPublishResult(note=note, body=body)

    def render_note(
        self,
        *,
        context: MergeRequestReviewContext,
        review_result: ReviewResult,
    ) -> str:
        """Render one deterministic review note body."""
        if review_result.classification == "no_findings":
            summary_line = (
                "No new actionable findings since the last reviewed SHA."
                if _is_follow_up_review(context)
                else "No actionable findings in this review pass."
            )
            return "\n".join(
                [
                    "## AI Review Summary",
                    "",
                    summary_line,
                    *_render_follow_up_lines(context, review_result),
                    *_render_confidence_lines(review_result),
                    "",
                    "Scope:",
                    f"- Reviewed merge request: `!{context.mr_iid}`",
                    f"- Reviewed commit SHA: `{context.head_sha}`",
                    f"- Files reviewed: {len(context.changed_files)}",
                ]
            )
        if review_result.classification == "manual_review_only":
            return "\n".join(
                [
                    "## AI Review Summary",
                    "",
                    "Bot assessment was insufficient for a trustworthy review decision.",
                    *_render_follow_up_lines(context, review_result),
                    "",
                    review_result.summary,
                    *_render_confidence_lines(review_result),
                    "",
                    "What this means:",
                    (
                        "- The bot could not assess this merge request reliably "
                        "with the available context."
                    ),
                    "- This is not an actionable finding by itself.",
                    "- Human review is still needed to decide whether the change is safe.",
                    "",
                    "Scope:",
                    f"- Reviewed merge request: `!{context.mr_iid}`",
                    f"- Reviewed commit SHA: `{context.head_sha}`",
                    f"- Files reviewed: {len(context.changed_files)}",
                ]
            )

        finding_lines = ["Findings:"]
        for index, finding in enumerate(review_result.findings, start=1):
            finding_lines.extend(
                [
                    f"{index}. [{finding.severity}] {finding.title} (`{finding.file_path}`)",
                    f"   Evidence: {finding.evidence}",
                    f"   {finding.explanation}",
                    f"   Follow-up: {finding.suggested_follow_up}",
                ]
            )

        return "\n".join(
            [
                "## AI Review Summary",
                "",
                *_render_follow_up_lines(context, review_result),
                review_result.summary,
                *_render_confidence_lines(review_result),
                "",
                *finding_lines,
                "",
                "Scope:",
                f"- Reviewed merge request: `!{context.mr_iid}`",
                f"- Reviewed commit SHA: `{context.head_sha}`",
                f"- Files reviewed: {len(context.changed_files)}",
            ]
        )


def _render_confidence_lines(review_result: ReviewResult) -> list[str]:
    """Render advisory confidence lines when present."""
    if review_result.review_confidence is None:
        return []
    lines = [
        "",
        "Confidence:",
        f"- Review confidence: {review_result.review_confidence:.2f}",
    ]
    if review_result.review_confidence_reason:
        lines.append(f"- Reason: {review_result.review_confidence_reason}")
    return lines


def _render_follow_up_lines(
    context: MergeRequestReviewContext,
    review_result: ReviewResult,
) -> list[str]:
    """Render light follow-up framing for repeated reviews on the same MR."""
    reconciliation = _reconcile_follow_up_review(
        context=context,
        review_result=review_result,
    )
    if reconciliation is None:
        return []
    lines = [
        (
            f"Follow-up review after the earlier bot pass on "
            f"`{reconciliation.prior_reviewed_head_sha}`."
        )
    ]
    if review_result.classification == "findings_present" and reconciliation.still_unresolved:
        lines.append(
            "Previously reported concerns may still be relevant; findings below "
            "focus on the current pass."
        )
    return [*lines, ""]


def _is_follow_up_review(context: MergeRequestReviewContext) -> bool:
    """Return whether the current review has bounded prior review context."""
    return bool(context.prior_review_context and context.prior_review_context.passes)


def _reconcile_follow_up_review(
    *,
    context: MergeRequestReviewContext,
    review_result: ReviewResult,
) -> FollowUpReviewReconciliation | None:
    """Compare the current review result to the latest prior pass only."""
    prior_review_context = context.prior_review_context
    if not prior_review_context or not prior_review_context.passes:
        return None

    latest_prior_pass = prior_review_context.passes[0]
    prior_findings_by_key = {
        _prior_finding_key(summary): FollowUpFindingStatus(
            summary=summary,
            file_path=_prior_finding_path(summary),
            status="appears_resolved",
        )
        for summary in [finding.summary for finding in latest_prior_pass.findings]
        if _prior_finding_key(summary) is not None
    }

    still_unresolved: list[FollowUpFindingStatus] = []
    new_findings: list[FollowUpFindingStatus] = []

    for finding in review_result.findings:
        finding_summary = f"{finding.file_path}: {finding.title}"
        finding_key = _current_finding_key(finding)
        finding_status = FollowUpFindingStatus(
            summary=finding_summary,
            file_path=finding.file_path,
            status="new",
        )
        if finding_key in prior_findings_by_key:
            still_unresolved.append(
                FollowUpFindingStatus(
                    summary=finding_summary,
                    file_path=finding.file_path,
                    status="still_unresolved",
                )
            )
            prior_findings_by_key.pop(finding_key, None)
        else:
            new_findings.append(finding_status)

    appears_resolved = list(prior_findings_by_key.values())
    return FollowUpReviewReconciliation(
        prior_reviewed_head_sha=latest_prior_pass.reviewed_head_sha,
        still_unresolved=still_unresolved,
        appears_resolved=appears_resolved,
        new_findings=new_findings,
    )


def _current_finding_key(finding: ReviewFinding) -> tuple[str, str, str]:
    """Build a conservative key for one current finding."""
    summary = f"{finding.file_path}: {finding.title}"
    return (
        finding.file_path.strip().lower(),
        finding.title.strip().lower(),
        _normalize_finding_text(summary),
    )


def _prior_finding_key(summary: str) -> tuple[str, str, str] | None:
    """Build a conservative key for one persisted prior finding summary."""
    parsed = _split_prior_summary(summary)
    if parsed is None:
        return None
    file_path, title = parsed
    return (
        file_path.strip().lower(),
        title.strip().lower(),
        _normalize_finding_text(summary),
    )


def _prior_finding_path(summary: str) -> str | None:
    """Return the file path from a persisted prior finding summary when available."""
    parsed = _split_prior_summary(summary)
    if parsed is None:
        return None
    return parsed[0]


def _split_prior_summary(summary: str) -> tuple[str, str] | None:
    """Split a persisted prior summary like `path: title` conservatively."""
    if ":" not in summary:
        return None
    file_path, title = summary.split(":", 1)
    if not file_path.strip() or not title.strip():
        return None
    return file_path.strip(), title.strip()


def _normalize_finding_text(text: str) -> str:
    """Normalize bounded finding text for conservative exact matching."""
    return re.sub(r"\s+", " ", text.strip().lower())
