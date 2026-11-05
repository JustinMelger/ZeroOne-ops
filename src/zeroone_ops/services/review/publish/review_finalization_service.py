"""Finalize review side effects after validation and continuity preparation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypedDict

from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    PublishableReviewArtifact,
    ReviewClassification,
    ReviewResult,
)
from zeroone_ops.models.review_overview import EarlierReviewFindings, ReviewOverviewPass
from zeroone_ops.models.state import ReviewInlineCommentDecision
from zeroone_ops.providers.review.platform import ReviewPlatformClientError
from zeroone_ops.services.review.publish.review_overview_codec import ReviewOverviewError
from zeroone_ops.services.review.publish.review_overview_coordinator import (
    ReviewOverviewCoordinator,
)
from zeroone_ops.services.review.publish.review_publisher import ReviewPublishResult

LOGGER = logging.getLogger(__name__)


class _ProjectionIdentity(TypedDict, total=False):
    review_pass_id: str


class ReviewProjectionService(Protocol):
    """Project a finalized review result onto provider-local state when supported."""

    def project_review(
        self,
        *,
        repository_id: str,
        context: ChangeRequestReviewContext,
        reviewed_sha: str,
        artifact: PublishableReviewArtifact | None = None,
        classification: ReviewClassification | None = None,
        review_note_id: int | None = None,
        review_note_url: str | None = None,
        review_pass_id: str | None = None,
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
        run_id: str | None = None,
        workflow_url: str | None = None,
    ) -> ReviewPublishResult:
        """Publish one artifact and return a publish result object."""


@dataclass(frozen=True)
class ReviewFinalizationResult:
    """Capture the final publish/projection side effects for one review run."""

    artifact: PublishableReviewArtifact
    review_result: ReviewResult
    note_id: int | None
    note_url: str | None
    inline_comment_decisions: list[ReviewInlineCommentDecision]
    publish_warning: str | None = None
    projection_warning: str | None = None
    error_message: str | None = None
    review_pass_id: str | None = None
    overview_pass: ReviewOverviewPass | None = None
    projection_retry_pending: bool = False
    projection_retry_warning: str | None = None
    earlier_findings: EarlierReviewFindings | None = None


class ReviewFinalizationService:
    """Run bounded publish and work-item projection side effects for one review artifact."""

    def __init__(
        self,
        *,
        review_publisher: ReviewArtifactPublisher,
        review_projection_factory: Callable[[], ReviewProjectionService | None] | None = None,
        overview_coordinator: ReviewOverviewCoordinator | None = None,
        workflow_url: str | None = None,
    ) -> None:
        """Initialize the finalization service."""
        self.review_publisher = review_publisher
        self.review_projection_factory = review_projection_factory
        self.overview_coordinator = overview_coordinator
        self.workflow_url = workflow_url

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

        publication_identity = (
            {"run_id": run_id, "workflow_url": self.workflow_url}
            if self.overview_coordinator is not None
            else {}
        )
        publish_result = self.review_publisher.publish_artifact(
            repository_id=repository_id,
            change_request_number=context.change_request_number,
            context=context,
            artifact=artifact,
            inline_comment_decisions=inline_comment_decisions,
            **publication_identity,
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

        projection_warning = (
            f"Review projection warning: {publish_result.authority_error}"
            if publish_result.authority_error is not None
            else None
        )
        if self.review_projection_factory is not None and publish_result.authority_error is None:
            try:
                review_projection_service = self.review_projection_factory()
                if review_projection_service is not None:
                    projection_identity: _ProjectionIdentity = {}
                    if publish_result.review_pass_id is not None:
                        projection_identity["review_pass_id"] = publish_result.review_pass_id
                    projection_result = review_projection_service.project_review(
                        repository_id=repository_id,
                        context=context,
                        artifact=finalized_artifact,
                        reviewed_sha=context.head_sha,
                        review_note_id=note_id,
                        review_note_url=note_url,
                        **projection_identity,
                    )
                    projection_action = getattr(projection_result, "action", None)
                    decision_warning = getattr(projection_result, "warning", None)
                    if isinstance(decision_warning, str):
                        projection_warning = f"Review projection warning: {decision_warning}"
                        LOGGER.warning(projection_warning)
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

        projection_retry_pending = projection_warning is not None
        projection_retry_warning = projection_warning
        if (
            self.overview_coordinator is not None
            and publish_result.review_pass_id is not None
            and publish_result.authority_error is None
        ):
            try:
                self.overview_coordinator.write_metadata(
                    repository_id=repository_id,
                    change_request_number=context.change_request_number,
                    head_sha=context.head_sha,
                    pass_id=publish_result.review_pass_id,
                    artifact=finalized_artifact,
                    inline_decisions=publish_result.inline_comment_decisions,
                    projection_pending=projection_warning is not None,
                    projection_warning=projection_warning,
                )
            except (ReviewOverviewError, ReviewPlatformClientError):
                metadata_warning = (
                    "Review projection metadata could not be synchronized; "
                    "the overview retains pending repair evidence."
                )
                publish_warning = " ".join(
                    part for part in (publish_warning, metadata_warning) if part
                )
                projection_retry_pending = True
                projection_retry_warning = projection_warning or metadata_warning

        return ReviewFinalizationResult(
            artifact=finalized_artifact,
            review_result=finalized_review_result,
            note_id=note_id,
            note_url=note_url,
            inline_comment_decisions=publish_result.inline_comment_decisions
            or inline_comment_decisions,
            publish_warning=publish_warning,
            projection_warning=projection_warning,
            review_pass_id=publish_result.review_pass_id,
            projection_retry_pending=projection_retry_pending,
            earlier_findings=publish_result.earlier_findings,
            projection_retry_warning=projection_retry_warning,
            overview_pass=(
                None
                if publish_result.overview_pass is None
                else publish_result.overview_pass.model_copy(
                    deep=True,
                    update={
                        "projection_pending": projection_retry_pending,
                        "projection_warning": projection_retry_warning,
                    },
                )
            ),
        )
