"""Inline-comment continuity preparation for review publishing."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.review import (
    MergeRequestReviewContext,
    PriorReviewInlineComment,
    PriorReviewPass,
    PublishableReviewArtifact,
    PublishableReviewFinding,
)


@dataclass(frozen=True)
class InlineCommentContinuityResult:
    """Capture inline-comment continuity preparation for one artifact."""

    artifact: PublishableReviewArtifact
    reused_inline_comment_count: int = 0


class ReviewInlineCommentContinuityService:
    """Prepare publish artifacts to reuse prior inline-comment continuity safely."""

    def apply(
        self,
        *,
        context: MergeRequestReviewContext,
        artifact: PublishableReviewArtifact,
    ) -> InlineCommentContinuityResult:
        """Mirror reusable prior inline-comment metadata onto current findings."""
        if artifact.classification != "findings_present":
            return InlineCommentContinuityResult(artifact=artifact)

        latest_pass = _latest_prior_pass(context)
        if latest_pass is None:
            return InlineCommentContinuityResult(artifact=artifact)

        prior_inline_by_identity = _published_prior_inline_comments_by_identity(latest_pass)
        if not prior_inline_by_identity:
            return InlineCommentContinuityResult(artifact=artifact)

        reused_inline_comment_count = 0
        updated_findings: list[PublishableReviewFinding] = []
        for finding in artifact.findings:
            if finding.inline_comment is not None or finding.stable_identity is None:
                updated_findings.append(finding)
                continue

            prior_inline_comment = prior_inline_by_identity.get(finding.stable_identity)
            if prior_inline_comment is None:
                updated_findings.append(finding)
                continue

            reused_inline_comment_count += 1
            updated_findings.append(
                finding.model_copy(update={"inline_comment": prior_inline_comment})
            )

        if reused_inline_comment_count == 0:
            return InlineCommentContinuityResult(artifact=artifact)
        return InlineCommentContinuityResult(
            artifact=artifact.model_copy(update={"findings": updated_findings}),
            reused_inline_comment_count=reused_inline_comment_count,
        )


def _latest_prior_pass(context: MergeRequestReviewContext) -> PriorReviewPass | None:
    """Return the latest available prior review pass when present."""
    if context.prior_review_context is None or not context.prior_review_context.passes:
        return None
    return context.prior_review_context.passes[0]


def _published_prior_inline_comments_by_identity(
    prior_pass: PriorReviewPass,
) -> dict[str, PriorReviewInlineComment]:
    """Index reusable published inline comments by canonical finding identity."""
    indexed_comments: dict[str, PriorReviewInlineComment] = {}
    for finding in prior_pass.findings:
        if finding.identity is None:
            continue
        if finding.inline_comment is None or finding.inline_comment.status != "published":
            continue
        indexed_comments.setdefault(finding.identity, finding.inline_comment)
    return indexed_comments
