"""Review publisher."""

from __future__ import annotations

from dataclasses import dataclass

from ai_sonar_bot.models.gitlab import MergeRequestNote
from ai_sonar_bot.models.review import MergeRequestReviewContext, ReviewResult
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
            return "\n".join(
                [
                    "## AI Review Summary",
                    "",
                    "No actionable findings in this review pass.",
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
