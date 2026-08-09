"""Provider-neutral remediation orchestration over shared execution services."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import FailureDetails, FailureStage, RunRecord, RunStatus, utc_now
from zeroone_ops.models.work_item import (
    PublicationRetryState,
    WorkItemExecutionFailure,
    WorkItemState,
)
from zeroone_ops.services.remediation.change_request_publisher import (
    build_remediation_change_request_publisher,
)
from zeroone_ops.services.remediation.control_plane import (
    RemediationControlPlane,
    build_remediation_control_plane,
)
from zeroone_ops.services.remediation.execution_service import ExecutionService
from zeroone_ops.services.remediation.publication_request_builder import (
    RemediationPublicationRequestBuilder,
)
from zeroone_ops.services.remediation.recovery.publication_retry_service import (
    PublicationRetryService,
)
from zeroone_ops.services.remediation.remediation_context_builder import (
    RemediationContextBuilder,
)
from zeroone_ops.services.shared.branch_revision_lookup import build_branch_revision_lookup
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary
from zeroone_ops.utils.git import build_remediation_branch_name

LOGGER = logging.getLogger(__name__)
_FAILURE_OUTPUT_LIMIT = 2_000


class _WorkItemIntakeResult(Protocol):
    """Expose one provider-local claimed work item to shared execution."""

    @property
    def selected_target(self) -> RemediationExecutionTarget | None:
        """Return the execution target selected from authoritative state."""

    @property
    def claimed_work_item(self) -> WorkItemState | None:
        """Return the selected work item after an optional persistent claim."""

    @property
    def item_count(self) -> int:
        """Return the number of authoritative work items considered."""

    @property
    def message(self) -> str:
        """Return the provider-local no-selection diagnostic."""


class WorkItemRemediationRunner:
    """Execute one claimed provider work item through the shared remediation core."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        run_state_service: RunStateService,
        execution_service: ExecutionService | None = None,
        remediation_control_plane: RemediationControlPlane | None = None,
        publication_retry_service: PublicationRetryService | None = None,
        execution_url_builder: Callable[[], str | None] | None = None,
    ) -> None:
        """Initialize shared remediation execution over one work-item control plane."""
        self.repo_root = repo_root
        self.config = config
        self.run_state_service = run_state_service
        self.execution_service = execution_service or ExecutionService(
            repo_root=repo_root,
            config=config,
        )
        self.remediation_control_plane = (
            remediation_control_plane or build_remediation_control_plane(config)
        )
        self.publication_retry_service = publication_retry_service
        self.execution_url_builder = execution_url_builder or (lambda: None)

    def run(self, *, record: RunRecord, active_dry_run: bool) -> RunSummary:
        """Select, execute, and project one provider work item."""
        if not active_dry_run and self.config.execution_mode != "ci":
            message = (
                "Work-item remediation live execution is only supported in CI mode. "
                "Use --dry-run locally."
            )
            return self.run_state_service.fail_run(
                record=record,
                error_message=message,
                failure=FailureDetails(stage=FailureStage.ISSUE_INTAKE, message=message),
            )

        intake_result = self._select_and_claim(
            persist=not active_dry_run,
            run_id=record.run_id,
        )
        selected_target = intake_result.selected_target
        claimed_work_item = intake_result.claimed_work_item
        if selected_target is None or claimed_work_item is None:
            return self.run_state_service.finish_no_issue(
                record=record,
                message=intake_result.message,
                issue_count=intake_result.item_count,
            )

        if claimed_work_item.publication_retry is not None:
            return self._retry_recorded_publication(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                record=record,
                active_dry_run=active_dry_run,
            )

        context = RemediationContextBuilder(self.repo_root, self.config).build(selected_target)
        if context is None:
            message = f"Context unavailable for remediation work item {selected_target.item_id}."
            failure = FailureDetails(stage=FailureStage.ISSUE_INTAKE, message=message)
            self._mark_blocked_best_effort(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                active_dry_run=active_dry_run,
                failure=failure,
                run_id=record.run_id,
            )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.FAILED,
                message=message,
                failure=failure,
            )

        execution_result = self.execution_service.execute_with_context(
            selected_issue=selected_target,
            context=context,
            dry_run=active_dry_run,
            branch_name=build_remediation_branch_name(
                branch_prefix=self.config.branch_prefix,
                source=selected_target.source_type,
                source_reference=selected_target.source_ref,
                file_path=selected_target.file_path,
                attempt_number=claimed_work_item.attempt_number,
            ),
        )
        if execution_result.failure is not None:
            self._mark_blocked_best_effort(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                active_dry_run=active_dry_run,
                failure=execution_result.failure,
                run_id=record.run_id,
            )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.FAILED,
                message=_failure_summary_message(execution_result.failure),
                branch_name=execution_result.branch_name,
                commit_sha=execution_result.commit_sha,
                failure=execution_result.failure,
            )

        if execution_result.final_status == RunStatus.REJECTED:
            self._mark_dismissed_best_effort(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                active_dry_run=active_dry_run,
            )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.REJECTED,
                message=execution_result.status_message,
                branch_name=execution_result.branch_name,
                commit_sha=execution_result.commit_sha,
            )

        if execution_result.change_request_url is not None:
            published_change_request = execution_result.published_change_request
            if published_change_request is None:
                message = (
                    "Published change request is missing identity required for work-item linkage."
                )
                failure = FailureDetails(stage=FailureStage.PUBLISH, message=message)
                self._mark_blocked_best_effort(
                    selected_target=selected_target,
                    claimed_work_item=claimed_work_item,
                    active_dry_run=active_dry_run,
                    failure=failure,
                    run_id=record.run_id,
                )
                return self.run_state_service.finish_work_item(
                    record=record,
                    work_item_id=selected_target.item_id,
                    status=RunStatus.FAILED,
                    message=message,
                    branch_name=execution_result.branch_name,
                    commit_sha=execution_result.commit_sha,
                    failure=failure,
                )
            self._sync_change_request_link_best_effort(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                published_change_request=published_change_request,
                active_dry_run=active_dry_run,
            )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.CHANGE_REQUEST_CREATED,
                message=execution_result.status_message,
                branch_name=execution_result.branch_name,
                commit_sha=execution_result.commit_sha,
                change_request_url=execution_result.change_request_url,
                change_request_action=execution_result.change_request_action,
            )

        self._mark_completed_best_effort(
            selected_target=selected_target,
            claimed_work_item=claimed_work_item,
            active_dry_run=active_dry_run,
        )
        return self.run_state_service.finish_work_item(
            record=record,
            work_item_id=selected_target.item_id,
            status=RunStatus.SELECTED,
            message=execution_result.status_message,
            branch_name=execution_result.branch_name,
            commit_sha=execution_result.commit_sha,
        )

    def _mark_blocked_best_effort(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        active_dry_run: bool,
        failure: FailureDetails | None = None,
        run_id: str | None = None,
    ) -> None:
        """Project an execution failure without replacing the primary outcome."""
        if active_dry_run:
            return
        try:
            self.remediation_control_plane.mark_execution_blocked(
                selected_issue=selected_target,
                existing_work_item=claimed_work_item,
                execution_failure=(
                    None
                    if failure is None or run_id is None
                    else self._build_execution_failure(failure=failure, run_id=run_id)
                ),
            )
        except Exception:
            LOGGER.warning("work-item blocked-state projection failed", exc_info=True)

    def _sync_change_request_link_best_effort(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        published_change_request: ChangeRequestInfo,
        active_dry_run: bool,
    ) -> None:
        """Link a published change request through the runner-owned control plane."""
        if active_dry_run:
            return
        try:
            self.remediation_control_plane.sync_change_request_link(
                selected_issue=selected_target,
                published_change_request=published_change_request,
                existing_work_item=claimed_work_item,
            )
        except Exception:
            LOGGER.warning("work-item change-request link projection failed", exc_info=True)

    def _retry_recorded_publication(
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
        if active_dry_run:
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.SELECTED,
                message="Dry-run would verify and retry recorded branch publication.",
                branch_name=publication_retry.branch_name,
                commit_sha=publication_retry.commit_sha,
            )
        retry_service = self.publication_retry_service or PublicationRetryService(
            branch_revision_lookup=build_branch_revision_lookup(self.config),
            change_request_publisher=build_remediation_change_request_publisher(self.config),
        )
        result = retry_service.retry(
            publication_retry=publication_retry,
            request=RemediationPublicationRequestBuilder(self.config).build(
                selected_issue=selected_target,
                source_branch=publication_retry.branch_name,
                change_summary="Retrying publication for the existing remediation branch.",
            ),
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
            LOGGER.warning("work-item publication retry projection failed", exc_info=True)

    def _mark_dismissed_best_effort(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        active_dry_run: bool,
    ) -> None:
        """Project an intentional rejection without replacing the primary outcome."""
        if active_dry_run:
            return
        try:
            self.remediation_control_plane.mark_execution_dismissed(
                selected_issue=selected_target,
                existing_work_item=claimed_work_item,
            )
        except Exception:
            LOGGER.warning("work-item dismissed-state projection failed", exc_info=True)

    def _mark_completed_best_effort(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
        active_dry_run: bool,
    ) -> None:
        """Project successful completion without replacing the primary outcome."""
        if active_dry_run:
            return
        try:
            self.remediation_control_plane.mark_execution_completed(
                selected_issue=selected_target,
                existing_work_item=claimed_work_item,
            )
        except Exception:
            LOGGER.warning("work-item completed-state projection failed", exc_info=True)

    def _select_and_claim(
        self,
        *,
        persist: bool,
        run_id: str,
    ) -> _WorkItemIntakeResult:
        """Return one provider-local work-item selection and claim."""
        raise NotImplementedError

    def _build_execution_failure(
        self,
        *,
        failure: FailureDetails,
        run_id: str,
    ) -> WorkItemExecutionFailure:
        """Build durable operator context for one failed remediation run."""
        return WorkItemExecutionFailure(
            stage=failure.stage.value,
            summary=failure.message,
            retry_count=failure.retry_count,
            run_id=run_id,
            occurred_at=utc_now(),
            failed_command=failure.failed_command,
            exit_code=failure.exit_code,
            execution_url=self.execution_url_builder(),
            validation_outcome=failure.validation_outcome,
        )


def _failure_summary_message(failure: FailureDetails) -> str:
    """Return a bounded CLI diagnostic without changing persisted failure state."""
    output = failure.stderr_excerpt or failure.stdout_excerpt
    if output is None or not output.strip():
        return failure.message

    excerpt = output.strip()
    if len(excerpt) > _FAILURE_OUTPUT_LIMIT:
        excerpt = f"{excerpt[:_FAILURE_OUTPUT_LIMIT]}\n... output truncated"
    return f"{failure.message}\n\nFailed command output:\n{excerpt}"
