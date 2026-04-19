"""Review publisher."""

from __future__ import annotations

from dataclasses import dataclass

from ai_sonar_bot.models.gitlab import MergeRequestNote
from ai_sonar_bot.models.review import (
    MergeRequestReviewContext,
    OverlapReconciliationResult,
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
        overlap_result: OverlapReconciliationResult | None = None,
    ) -> ReviewPublishResult:
        """Publish one deterministic review summary note."""
        body = self.render_note(
            context=context,
            review_result=review_result,
            overlap_result=overlap_result,
        )
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
        overlap_result: OverlapReconciliationResult | None = None,
    ) -> str:
        """Render one deterministic review note body."""
        if review_result.classification == "no_findings":
            summary_line = (
                "No new actionable findings since the last reviewed SHA."
                if overlap_result is not None
                else "No actionable findings in this review pass."
            )
            return "\n".join(
                [
                    "Hi,",
                    "",
                    "Here are your review notes.",
                    "",
                    summary_line,
                    *_render_follow_up_lines(review_result, overlap_result),
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
                    "Hi,",
                    "",
                    "Here are your review notes.",
                    "",
                    "Bot assessment was insufficient for a trustworthy review decision.",
                    *_render_follow_up_lines(review_result, overlap_result),
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
                "Hi,",
                "",
                "Here are your review notes.",
                "",
                *_render_follow_up_lines(review_result, overlap_result),
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
    review_result: ReviewResult,
    overlap_result: OverlapReconciliationResult | None,
) -> list[str]:
    """Render light follow-up framing for repeated reviews on the same MR."""
    if overlap_result is None:
        return []

    lines = [
        (
            f"Follow-up review after the earlier bot pass on "
            f"`{overlap_result.prior_reviewed_head_sha}`."
        )
    ]
    lines.extend(_render_overlap_summary_lines(overlap_result, review_result))
    return [*lines, ""]


def _render_overlap_summary_lines(
    overlap_result: OverlapReconciliationResult,
    review_result: ReviewResult,
) -> list[str]:
    """Render concise follow-up lines from normalized overlap outcomes."""
    still_unresolved = [
        resolution
        for resolution in overlap_result.resolutions
        if resolution.outcome == "still_unresolved"
    ]
    new_in_this_pass = [
        resolution
        for resolution in overlap_result.resolutions
        if resolution.outcome == "new_in_this_pass"
    ]
    no_longer_present = [
        resolution
        for resolution in overlap_result.resolutions
        if resolution.outcome == "no_longer_present"
    ]
    overlap_ambiguous = [
        resolution
        for resolution in overlap_result.resolutions
        if resolution.outcome == "overlap_ambiguous"
    ]

    lines: list[str] = []
    if review_result.classification == "manual_review_only":
        if still_unresolved or overlap_ambiguous:
            lines.append(
                "This pass may still relate to an earlier concern, but the current "
                "review was not confident enough to verify continuity fully."
            )
        return lines

    if review_result.classification == "no_findings":
        if no_longer_present:
            lines.append("The earlier concern from the last pass no longer appears present.")
        if overlap_ambiguous:
            lines.append(
                "This pass may overlap with an earlier concern, but the overlap "
                "is not fully clear from the current changes."
            )
        return lines

    if still_unresolved:
        lines.append("An earlier concern from the last pass still appears unresolved.")
    if no_longer_present and new_in_this_pass:
        lines.append(
            "One earlier concern no longer appears present, but this pass also "
            "introduces a new concern."
        )
    elif no_longer_present:
        lines.append("One earlier concern from the last pass no longer appears present.")
    elif new_in_this_pass:
        lines.append("This pass also introduces a new concern.")

    if overlap_ambiguous:
        lines.append(
            "This pass may overlap with an earlier concern, but the overlap is "
            "not fully clear from the current changes."
        )
    return lines
