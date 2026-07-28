"""Finalize review side effects after validation and continuity preparation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    PublishableReviewArtifact,
    ReviewClassification,
    ReviewResult,
)
from zeroone_ops.models.state import ReviewInlineCommentDecision
from zeroone_ops.services.review.publish.review_dashboard_updater import (
    ReviewDashboardUpdater,
)
from zeroone_ops.services.review.publish.review_publisher import ReviewPublishResult

LOGGER = logging.getLogger(__name__)


class ReviewProjectionService(Protocol):
    """Project a finalized review result onto provider-local state when supported."""

    def project_review(
        self,
        *,
        repository_id: str,
        context: ChangeRequestReviewContext,
        classification: ReviewClassification,
        reviewed_sha: str,
        review_note_url: str | None,
    ) -> object:
        """Project one finalized review result."""


class ReviewArtifactPublisher(Protocol):
    """Publish one finalized review artifact."""

    def publish_artifact(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        context: ChangeRequestReviewContext,
        artifact: PublishableReviewArtifact,
        inline_comment_decisions: list[ReviewInlineCommentDecision] | None = None,
    ) -> ReviewPublishResult:
        """Publish one artifact and return a publish result object."""


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
    projection_warning: str | None = None
    error_message: str | None = None


class ReviewFinalizationService:
    """Run bounded publish and dashboard side effects for one review artifact."""

    def __init__(
        self,
        *,
        review_publisher: ReviewArtifactPublisher,
        dashboard_updater: ReviewDashboardUpdater | None,
        review_projection_factory: Callable[[], ReviewProjectionService | None] | None = None,
    ) -> None:
        """Initialize the finalization service."""
        self.review_publisher = review_publisher
        self.dashboard_updater = dashboard_updater
        self.review_projection_factory = review_projection_factory

    def finalize(
        self,
        *,
        run_id: str,
        repository_id: str,
        active_dry_run: bool,
        change_request: ChangeRequestReviewCandidate,
        context: ChangeRequestReviewContext,
        artifact: PublishableReviewArtifact,
        inline_comment_decisions: list[ReviewInlineCommentDecision],
    ) -> ReviewFinalizationResult:
        """Publish the final artifact and mirror the result when not in dry-run mode."""
        if active_dry_run:
            LOGGER.info(
                "review dry-run skipped publication",
                extra={
                    "run_id": run_id,
                    "change_request_number": context.change_request_number,
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
            repository_id=repository_id,
            change_request_number=context.change_request_number,
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
                    "change_request_number": context.change_request_number,
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
                        "change_request_number": context.change_request_number,
                        "head_sha": context.head_sha,
                        "warning": publish_warning,
                    },
                )

        dashboard_warning = None
        if self.dashboard_updater is not None:
            dashboard_update = self.dashboard_updater.update(
                project_id=repository_id,
                merge_request=change_request,
                review_result=finalized_review_result,
            )
            dashboard_warning = dashboard_update.error_message
            if dashboard_warning is None:
                LOGGER.info(
                    "review dashboard mirrored",
                    extra={
                        "run_id": run_id,
                        "change_request_number": context.change_request_number,
                        "head_sha": context.head_sha,
                        "dashboard_issue_url": dashboard_update.dashboard_issue_url,
                    },
                )
            else:
                LOGGER.warning(
                    "review dashboard mirror warning",
                    extra={
                        "run_id": run_id,
                        "change_request_number": context.change_request_number,
                        "head_sha": context.head_sha,
                    },
                )

        projection_warning = None
        if self.review_projection_factory is not None:
            try:
                review_projection_service = self.review_projection_factory()
                if review_projection_service is not None:
                    projection_result = review_projection_service.project_review(
                        repository_id=repository_id,
                        context=context,
                        classification=finalized_review_result.classification,
                        reviewed_sha=context.head_sha,
                        review_note_url=note_url,
                    )
                    projection_action = getattr(projection_result, "action", None)
                    if projection_action in {"updated", "unchanged"}:
                        LOGGER.info(
                            "review projection mirrored",
                            extra={
                                "run_id": run_id,
                                "change_request_number": context.change_request_number,
                                "head_sha": context.head_sha,
                                "projection_action": projection_action,
                            },
                        )
                    elif (
                        projection_action == "no_linked_work_item"
                        and context.remediation_context is not None
                    ):
                        projection_warning = (
                            "Review projection warning: no authoritative work item was linked "
                            "to this remediation change request."
                        )
                        LOGGER.warning(
                            "review projection missing authoritative remediation link",
                            extra={
                                "run_id": run_id,
                                "change_request_number": context.change_request_number,
                                "head_sha": context.head_sha,
                            },
                        )
            except Exception as error:
                projection_warning = f"Review projection warning: {error}"
                LOGGER.warning(
                    "review projection warning",
                    extra={
                        "run_id": run_id,
                        "change_request_number": context.change_request_number,
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
            projection_warning=projection_warning,
        )
