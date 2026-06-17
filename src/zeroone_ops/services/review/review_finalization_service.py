"""Finalize review side effects after validation and continuity preparation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from zeroone_ops.models.review import (
    PublishableReviewArtifact,
    PullRequestReviewCandidate,
    PullRequestReviewContext,
    ReviewResult,
)
from zeroone_ops.models.state import ReviewInlineCommentDecision
from zeroone_ops.services.review.review_dashboard_updater import ReviewDashboardUpdater
from zeroone_ops.services.review.review_publisher import ReviewPublisher

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewFinalizationResult:
    """Capture the final publish/dashboard side effects for one review run."""

    artifact: PublishableReviewArtifact
    review_result: ReviewResult
    note_id: int | None
    note_url: str | None
    inline_comment_decisions: list[ReviewInlineCommentDecision]
    publish_warning: str | None = None
    dashboard_warning: str | None = None
    error_message: str | None = None


class ReviewFinalizationService:
    """Run bounded publish and dashboard side effects for one review artifact."""

    def __init__(
        self,
        *,
        review_publisher: ReviewPublisher,
        dashboard_updater: ReviewDashboardUpdater,
    ) -> None:
        """Initialize the finalization service."""
        self.review_publisher = review_publisher
        self.dashboard_updater = dashboard_updater

    def finalize(
        self,
        *,
        run_id: str,
        project_id: str,
        active_dry_run: bool,
        merge_request: PullRequestReviewCandidate,
        context: PullRequestReviewContext,
        artifact: PublishableReviewArtifact,
        inline_comment_decisions: list[ReviewInlineCommentDecision],
    ) -> ReviewFinalizationResult:
        """Publish the final artifact and mirror the result when not in dry-run mode."""
        if active_dry_run:
            LOGGER.info(
                "review dry-run skipped publication",
                extra={
                    "run_id": run_id,
                    "mr_iid": context.mr_iid,
                    "head_sha": context.head_sha,
                },
            )
            return ReviewFinalizationResult(
                artifact=artifact,
                review_result=artifact.to_review_result(),
                note_id=None,
                note_url=None,
                inline_comment_decisions=[],
            )

        publish_result = self.review_publisher.publish_artifact(
            project_id=project_id,
            merge_request_iid=context.mr_iid,
            context=context,
            artifact=artifact,
            inline_comment_decisions=inline_comment_decisions,
        )
        if publish_result.error_message is not None:
            return ReviewFinalizationResult(
                artifact=artifact,
                review_result=artifact.to_review_result(),
                note_id=None,
                note_url=None,
                inline_comment_decisions=inline_comment_decisions,
                error_message=publish_result.error_message,
            )

        finalized_artifact = publish_result.artifact
        finalized_review_result = finalized_artifact.to_review_result()
        note_id = None if publish_result.note is None else publish_result.note.id
        note_url = None if publish_result.note is None else publish_result.note.web_url
        publish_warning = publish_result.warning_message

        if publish_result.note is not None:
            LOGGER.info(
                "review note published",
                extra={
                    "run_id": run_id,
                    "mr_iid": context.mr_iid,
                    "head_sha": context.head_sha,
                    "note_id": publish_result.note.id,
                    "note_url": publish_result.note.web_url,
                },
            )
            if publish_warning is not None:
                LOGGER.warning(
                    "review inline comment transport warning",
                    extra={
                        "run_id": run_id,
                        "mr_iid": context.mr_iid,
                        "head_sha": context.head_sha,
                        "warning": publish_warning,
                    },
                )

        dashboard_update = self.dashboard_updater.update(
            project_id=project_id,
            merge_request=merge_request,
            review_result=finalized_review_result,
        )
        dashboard_warning = dashboard_update.error_message
        if dashboard_warning is None:
            LOGGER.info(
                "review dashboard mirrored",
                extra={
                    "run_id": run_id,
                    "mr_iid": context.mr_iid,
                    "head_sha": context.head_sha,
                    "dashboard_issue_url": dashboard_update.dashboard_issue_url,
                },
            )
        else:
            LOGGER.warning(
                "review dashboard mirror warning",
                extra={
                    "run_id": run_id,
                    "mr_iid": context.mr_iid,
                    "head_sha": context.head_sha,
                },
            )

        return ReviewFinalizationResult(
            artifact=finalized_artifact,
            review_result=finalized_review_result,
            note_id=note_id,
            note_url=note_url,
            inline_comment_decisions=publish_result.inline_comment_decisions
            or inline_comment_decisions,
            publish_warning=publish_warning,
            dashboard_warning=dashboard_warning,
        )
