"""Repair a pending projection without rerunning or republishing review."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    PublishableReviewArtifact,
    ReviewClassification,
)
from zeroone_ops.models.state import ChangeRequestReviewState
from zeroone_ops.services.review.context.review_context_builder import ReviewContextBuilder
from zeroone_ops.services.review.continuity.review_continuity_context_service import (
    AUTHORITATIVE_REVIEW_CLASSIFICATIONS,
)
from zeroone_ops.services.review.publish.review_finalization_service import ReviewProjectionService
from zeroone_ops.services.review.state.review_state_service import ReviewStateService


class _ProjectionAction(Protocol):
    """Describe the existing result attribute consumed by repair logging."""

    action: str


class ReviewProjectionRepairService:
    """Coordinate projection retries while leaving state persistence to its owner."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        review_state_service: ReviewStateService,
        review_projection_factory: Callable[[], ReviewProjectionService | None],
        logger: logging.Logger,
    ) -> None:
        """Retain a lazy factory without constructing provider dependencies."""
        self.repo_root = repo_root
        self.config = config
        self.review_state_service = review_state_service
        self.review_projection_factory = review_projection_factory
        self.logger = logger

    def retry_if_needed(
        self,
        *,
        run_id: str,
        repository_id: str,
        change_request: ChangeRequestReviewCandidate,
        review_state: ChangeRequestReviewState | None,
        active_dry_run: bool,
    ) -> str | None:
        """Retry one pending projection side effect without re-entering review analysis."""
        if active_dry_run or review_state is None or not review_state.projection_retry_pending:
            return None
        warning_message = self._repair_same_sha_projection(
            run_id=run_id,
            repository_id=repository_id,
            change_request=change_request,
            classification=review_state.status,
            note_id=review_state.note_id,
            note_url=review_state.note_url,
            artifact=review_state.projection_artifact,
        )
        self.review_state_service.update_projection_retry_state(
            change_request_number=change_request.change_request_number,
            head_sha=change_request.head_sha,
            last_run_id=run_id,
            pending=warning_message is not None,
            warning=warning_message,
        )
        if warning_message is not None:
            return warning_message
        return "Repaired pending review projection."

    def _repair_same_sha_projection(
        self,
        *,
        run_id: str,
        repository_id: str,
        change_request: ChangeRequestReviewCandidate,
        classification: str | None,
        note_id: int | None,
        note_url: str | None,
        artifact: PublishableReviewArtifact | None = None,
    ) -> str | None:
        """Retry projection only for one previously published same-SHA review."""
        if classification not in AUTHORITATIVE_REVIEW_CLASSIFICATIONS:
            return (
                "Review projection warning: authoritative same-SHA classification was unavailable."
            )
        if note_id is None and note_url is None:
            return "Review projection warning: persisted review note reference was unavailable."
        if artifact is None and classification == "findings_present":
            return (
                "Review projection warning: persisted structured findings are unavailable; "
                "a new review is required."
            )
        context_result = ReviewContextBuilder(
            repo_root=self.repo_root,
            config=self.config,
        ).build(change_request)
        context = context_result.context
        if context is None:
            return f"Review projection warning: {context_result.message}"
        projection_service = self.review_projection_factory()
        if projection_service is None:
            return None
        try:
            projection_result = projection_service.project_review(
                repository_id=repository_id,
                context=context,
                artifact=artifact
                or PublishableReviewArtifact(
                    classification=cast(ReviewClassification, classification),
                    summary="Previously published review projection repair.",
                ),
                reviewed_sha=context.head_sha,
                review_note_id=note_id,
                review_note_url=note_url,
            )
        except Exception as error:
            self.logger.warning(
                "review same-sha projection repair failed",
                extra={
                    "run_id": run_id,
                    "change_request_number": change_request.change_request_number,
                    "head_sha": change_request.head_sha,
                },
            )
            return f"Review projection warning: {error}"
        self.logger.info(
            "review same-sha projection repair completed",
            extra={
                "run_id": run_id,
                "change_request_number": change_request.change_request_number,
                "head_sha": change_request.head_sha,
                "projection_action": cast(_ProjectionAction, projection_result).action,
            },
        )
        warning = getattr(projection_result, "warning", None)
        if isinstance(warning, str):
            return f"Review projection warning: {warning}"
        return None
