"""Review publisher."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from zeroone_ops.models.gitlab import MergeRequestNote
from zeroone_ops.models.review import (
    MergeRequestReviewContext,
    OverlapReconciliationResult,
    PublishableReviewArtifact,
    ReconciledReviewDecision,
    ReviewResult,
)
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.providers.gitlab_review_client import GitLabReviewClientProtocol
from zeroone_ops.services.review.review_artifact_builder import ReviewArtifactBuilder


@dataclass(frozen=True)
class ReviewPublishResult:
    """Capture the outcome of publishing a review note."""

    note: MergeRequestNote | None
    body: str
    error_message: str | None = None


class ReviewPublisher:
    """Render and publish deterministic merge-request review notes."""

    def __init__(self, review_client: GitLabReviewClientProtocol) -> None:
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
        artifact = _artifact_from_review_result(
            review_result=review_result,
            overlap_result=overlap_result,
        )
        body = self.render_artifact(
            context=context,
            artifact=artifact,
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

    def publish_artifact(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        context: MergeRequestReviewContext,
        artifact: PublishableReviewArtifact,
    ) -> ReviewPublishResult:
        """Publish one note from a publish-shaped review artifact."""
        body = self.render_artifact(
            context=context,
            artifact=artifact,
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
        """Render one deterministic review note body from the legacy review result shape."""
        artifact = _artifact_from_review_result(
            review_result=review_result,
            overlap_result=overlap_result,
        )
        return self.render_artifact(context=context, artifact=artifact)

    def render_artifact(
        self,
        *,
        context: MergeRequestReviewContext,
        artifact: PublishableReviewArtifact,
    ) -> str:
        """Render one deterministic review note body from a publish-shaped artifact."""
        lines = [
            "Hi,",
            "",
            "Here are your review notes.",
            "",
        ]

        if artifact.classification == "no_findings":
            lines.extend(
                [
                    artifact.summary,
                    *artifact.follow_up_lines,
                    *_render_confidence_lines(artifact),
                ]
            )
        elif artifact.classification == "manual_review_only":
            lines.extend(
                [
                    "Bot assessment was insufficient for a trustworthy review decision.",
                    *artifact.follow_up_lines,
                    "",
                    artifact.summary,
                    *_render_confidence_lines(artifact),
                    "",
                    "What this means:",
                    (
                        "- The bot could not assess this merge request reliably "
                        "with the available context."
                    ),
                    "- This is not an actionable finding by itself.",
                    "- Human review is still needed to decide whether the change is safe.",
                ]
            )
        else:
            finding_lines = ["Findings:"]
            for index, finding in enumerate(artifact.findings, start=1):
                finding_lines.extend(
                    [
                        f"{index}. [{finding.severity}] {finding.title} (`{finding.file_path}`)",
                        f"   Evidence: {finding.evidence}",
                        f"   {finding.explanation}",
                        f"   Follow-up: {finding.suggested_follow_up}",
                    ]
                )
            lines.extend(
                [
                    *artifact.follow_up_lines,
                    artifact.summary,
                    *_render_confidence_lines(artifact),
                    "",
                    *finding_lines,
                ]
            )

        lines.extend(
            [
                "",
                "Scope:",
                f"- Reviewed merge request: `!{context.mr_iid}`",
                f"- Reviewed commit SHA: `{context.head_sha}`",
                f"- Files reviewed: {len(context.changed_files)}",
                "",
                *_render_machine_safe_block(context=context, artifact=artifact),
            ]
        )
        return "\n".join(lines)


def _render_confidence_lines(artifact: PublishableReviewArtifact) -> list[str]:
    """Render advisory confidence lines when present."""
    if artifact.review_confidence is None:
        return []
    lines = [
        "",
        "Confidence:",
        f"- Review confidence: {artifact.review_confidence:.2f}",
    ]
    if artifact.review_confidence_reason:
        lines.append(f"- Reason: {artifact.review_confidence_reason}")
    return lines


def _artifact_from_review_result(
    *,
    review_result: ReviewResult,
    overlap_result: OverlapReconciliationResult | None,
) -> PublishableReviewArtifact:
    """Adapt the legacy review-result path into the publish-shaped artifact shape."""
    artifact_builder = ReviewArtifactBuilder()
    return artifact_builder.build(
        reconciled_decision=_reconciled_decision_from_review_result(review_result),
        overlap_result=overlap_result,
    ).artifact


def _render_machine_safe_block(
    *,
    context: MergeRequestReviewContext,
    artifact: PublishableReviewArtifact,
) -> list[str]:
    """Render one bounded machine-safe note block for later MR reconstruction."""
    payload = {
        "schema": "ai-sonar-bot/review-note/v1",
        "reviewed_merge_request_iid": context.mr_iid,
        "reviewed_head_sha": context.head_sha,
        "classification": artifact.classification,
        "summary": artifact.summary,
        "findings_count": len(artifact.findings),
        "findings": [
            {
                "summary": f"{finding.file_path}: {finding.title}",
                "severity": finding.severity,
                "file_path": finding.file_path,
                "title": finding.title,
                "symbol": finding.symbol,
                "issue_kind": finding.issue_kind,
                "region_hint": finding.region_hint,
            }
            for finding in artifact.findings
        ],
    }
    return [
        "<!-- ai-sonar-bot:review-note:v1",
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        "-->",
    ]


def _reconciled_decision_from_review_result(
    review_result: ReviewResult,
) -> ReconciledReviewDecision:
    """Build a minimal reconciled decision adapter for legacy publisher calls."""
    return ReconciledReviewDecision.from_review_result(
        review_result,
        prior_review_context_used=False,
        same_sha_review=False,
        repair_allowed=review_result.classification != "manual_review_only",
        reconciled_at=datetime.now(UTC),
        pipeline_version="review-legacy-adapter",
    )
