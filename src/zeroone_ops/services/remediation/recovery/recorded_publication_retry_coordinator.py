"""Coordinate recorded publication without rerunning remediation execution."""

from __future__ import annotations

import logging
from collections.abc import Callable

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import FailureDetails, FailureStage, RunRecord, RunStatus
from zeroone_ops.models.work_item import (
    PublicationRetryState,
    WorkItemSemanticSafety,
    WorkItemState,
)
from zeroone_ops.services.remediation.batch_execution_scope_service import (
    BatchExecutionScopeService,
)
from zeroone_ops.services.remediation.control_plane import RemediationControlPlane
from zeroone_ops.services.remediation.publication_request_builder import (
    RemediationPublicationRequestBuilder,
)
from zeroone_ops.services.remediation.recovery.publication_retry_service import (
    PublicationRetryResult,
    PublicationRetryService,
)
from zeroone_ops.services.shared.projection_payload import ProjectionSizeExceeded
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary


class RecordedPublicationRetryCoordinator:
    """Reuse recorded scope and delegate publication and authoritative state writes."""

    def __init__(
        self,
        *,
        config: AppConfig,
        run_state_service: RunStateService,
        remediation_control_plane: RemediationControlPlane,
        retry_service_factory: Callable[[], PublicationRetryService],
        logger: logging.Logger,
    ) -> None:
        """Retain dependencies without loading provider settings or constructing clients."""
        self.config = config
        self.run_state_service = run_state_service
        self.remediation_control_plane = remediation_control_plane
        self.retry_service_factory = retry_service_factory
        self.logger = logger

    def run(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        record: RunRecord,
        active_dry_run: bool,
    ) -> RunSummary:
        """Retry only a recorded branch publication through the normal remediation runner."""
        publication_retry = claimed_work_item.publication_retry
        if publication_retry is None:  # pragma: no cover - guarded by caller
            raise ValueError("Publication retry requires recorded retry state.")
        if selected_target.batch is not None:
            decision = BatchExecutionScopeService().resolve(claimed_work_item, None)
            if decision.disposition != "execute":
                if not active_dry_run:
                    self._mark_publish_retry_blocked_best_effort(
                        selected_target=selected_target,
                        claimed_work_item=claimed_work_item,
                        publication_retry=publication_retry,
                    )
                failure = FailureDetails(
                    stage=FailureStage.PUBLISH,
                    message=decision.reason or "Recorded batch scope is unavailable.",
                )
                return self.run_state_service.finish_work_item(
                    record=record,
                    work_item_id=selected_target.item_id,
                    status=RunStatus.FAILED,
                    message=failure.message,
                    failure=failure,
                )
            selected_target = selected_target.model_copy(update={"batch_attempt": decision.attempt})
        if active_dry_run:
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.SELECTED,
                message="Dry-run would verify and retry recorded branch publication.",
                branch_name=publication_retry.branch_name,
                commit_sha=publication_retry.commit_sha,
            )
        retry_service = self.retry_service_factory()
        try:
            result = retry_service.retry(
                publication_retry=publication_retry,
                request=RemediationPublicationRequestBuilder(self.config).build(
                    selected_issue=selected_target,
                    source_branch=publication_retry.branch_name,
                    change_summary="Retrying publication for the existing remediation branch.",
                    remediation_intent=publication_retry.remediation_intent,
                    semantic_safety=publication_retry.semantic_safety,
                ),
            )
        except ProjectionSizeExceeded:
            result = PublicationRetryResult(
                error_message="Recorded batch publication exceeds the application payload budget."
            )
        if not result.succeeded or result.change_request is None:
            message = result.error_message or "Recorded branch publication retry failed."
            failure = FailureDetails(stage=FailureStage.PUBLISH, message=message)
            self._mark_publish_retry_blocked_best_effort(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                publication_retry=publication_retry,
            )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.FAILED,
                message=message,
                branch_name=publication_retry.branch_name,
                commit_sha=publication_retry.commit_sha,
                failure=failure,
            )
        self.remediation_control_plane.sync_change_request_link(
            selected_issue=selected_target,
            published_change_request=result.change_request,
            existing_work_item=claimed_work_item,
            semantic_safety=(
                None
                if publication_retry.semantic_safety is None
                else WorkItemSemanticSafety(assessment=publication_retry.semantic_safety)
            ),
        )
        return self.run_state_service.finish_work_item(
            record=record,
            work_item_id=selected_target.item_id,
            status=RunStatus.CHANGE_REQUEST_CREATED,
            message="Recorded branch publication retry completed.",
            branch_name=publication_retry.branch_name,
            commit_sha=publication_retry.commit_sha,
            change_request_url=result.change_request.web_url,
            change_request_action=result.action,
        )

    def _mark_publish_retry_blocked_best_effort(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        publication_retry: PublicationRetryState,
    ) -> None:
        """Preserve retry state when a repeated publication attempt fails."""
        try:
            self.remediation_control_plane.mark_publish_blocked(
                selected_issue=selected_target,
                existing_work_item=claimed_work_item,
                publication_retry=publication_retry,
            )
        except Exception:
            self.logger.warning("work-item publication retry projection failed", exc_info=True)
