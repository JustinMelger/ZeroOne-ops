"""Dashboard remediation workflow runner."""

from __future__ import annotations

import logging
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationWorkItem
from zeroone_ops.models.state import AppState, FailureDetails, FailureStage, RunRecord
from zeroone_ops.models.work_item import PublicationRetryState, WorkItemState
from zeroone_ops.services.control_plane.work_items.remediation_work_item_promotion_service import (
    RemediationWorkItemPromotionContext,
)
from zeroone_ops.services.dashboard.dashboard_item_intake import (
    DashboardItemIntakeService,
)
from zeroone_ops.services.dashboard.dashboard_item_normalizer import (
    DashboardItemNormalizer,
)
from zeroone_ops.services.dashboard.dashboard_remediation_updater import (
    DashboardRemediationUpdater,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
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
from zeroone_ops.services.remediation.remediation_execution_adapter import (
    remediation_work_item_to_execution_target,
)
from zeroone_ops.services.shared.branch_revision_lookup import build_branch_revision_lookup
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary
from zeroone_ops.utils.git import build_remediation_branch_name

LOGGER = logging.getLogger(__name__)


class DashboardRemediationRunner:
    """Run the dashboard remediation workflow with injected dependencies."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        dashboard_service: DashboardService,
        run_state_service: RunStateService,
        remediation_control_plane: RemediationControlPlane | None = None,
        publication_retry_service: PublicationRetryService | None = None,
    ) -> None:
        """Initialize the remediation workflow runner."""
        self.repo_root = repo_root
        self.config = config
        self.dashboard_service = dashboard_service
        self.run_state_service = run_state_service
        self._remediation_control_plane_override = remediation_control_plane
        self._remediation_control_plane: RemediationControlPlane | None = None
        self.publication_retry_service = publication_retry_service

    def run(
        self,
        *,
        project_id: str,
        state: AppState,
        run_id: str,
        record: RunRecord,
        active_dry_run: bool,
    ) -> RunSummary:
        """Run one dashboard remediation workflow."""
        if not active_dry_run and self.config.execution_mode != "ci":
            message = (
                "Dashboard remediation live execution is only supported in CI mode. "
                "Use --dry-run locally."
            )
            return self.run_state_service.fail_run(
                record=record,
                error_message=message,
                failure=FailureDetails(
                    stage=FailureStage.ISSUE_INTAKE,
                    message=message,
                ),
            )

        intake_result = DashboardItemIntakeService(
            repo_root=self.repo_root,
            config=self.config,
            dashboard_service=self.dashboard_service,
        ).select_item(
            project_id=project_id,
            state=state,
        )
        recovered_stale_item_ids = getattr(intake_result, "recovered_stale_item_ids", ())
        if intake_result.selected_item is None:
            return self.run_state_service.finish_no_issue(
                record=record,
                message=_with_dashboard_recovery_note(
                    intake_result.message,
                    recovered_stale_item_ids=recovered_stale_item_ids,
                ),
                issue_count=intake_result.item_count,
            )

        self.run_state_service.dashboard.mark_selected(
            record=record,
            dashboard_item_id=intake_result.selected_item.id,
        )

        normalization_result = DashboardItemNormalizer().normalize(intake_result.selected_item)
        if normalization_result.work_item is None:
            if not active_dry_run:
                DashboardRemediationUpdater(self.dashboard_service).mark_rejected(
                    project_id=project_id,
                    dashboard_item_id=intake_result.selected_item.id,
                    run_id=run_id,
                    rejection_reason=normalization_result.message,
                )
            return self.run_state_service.dashboard.reject_item(
                record=record,
                dashboard_item_id=intake_result.selected_item.id,
                branch_name=None,
                message=_with_dashboard_recovery_note(
                    normalization_result.message,
                    recovered_stale_item_ids=recovered_stale_item_ids,
                ),
            )

        work_item = normalization_result.work_item
        if intake_result.selected_item.publication_retry is not None:
            return self._retry_recorded_publication(
                project_id=project_id,
                work_item=work_item,
                record=record,
                active_dry_run=active_dry_run,
                recovered_stale_item_ids=recovered_stale_item_ids,
            )
        live_dashboard_updates = not active_dry_run and self.config.execution_mode == "ci"
        promoted_work_item = None
        if live_dashboard_updates:
            promoted_work_item = self._materialize_promoted_work_item_best_effort(
                work_item=work_item,
                promotion_context=RemediationWorkItemPromotionContext(
                    selected_for_remediation=True,
                ),
            )
        context = RemediationContextBuilder(self.repo_root, self.config).build(work_item)
        if context is None:
            message = f"Context unavailable for dashboard item {work_item.dashboard_item_id}."
            self._mark_execution_blocked_best_effort(
                work_item=work_item,
                existing_work_item=promoted_work_item,
            )
            if not active_dry_run:
                DashboardRemediationUpdater(self.dashboard_service).mark_failed(
                    project_id=project_id,
                    dashboard_item_id=work_item.dashboard_item_id,
                    run_id=run_id,
                    error_message=message,
                )
            return self.run_state_service.dashboard.fail_item(
                record=record,
                dashboard_item_id=work_item.dashboard_item_id,
                error_message=_with_dashboard_recovery_note(
                    message,
                    recovered_stale_item_ids=recovered_stale_item_ids,
                ),
                failure=FailureDetails(
                    stage=FailureStage.ISSUE_INTAKE,
                    message=message,
                ),
            )

        retry_count = intake_result.selected_item.retry_count or 0
        if intake_result.selected_item.retry_eligible:
            retry_count += 1
        if live_dashboard_updates:
            in_progress_result = DashboardRemediationUpdater(
                self.dashboard_service
            ).mark_in_progress(
                project_id=project_id,
                dashboard_item_id=work_item.dashboard_item_id,
                run_id=run_id,
                retry_count=retry_count,
                retry_eligible=False,
                retry_block_reason=None,
            )
            if in_progress_result.error_message is not None:
                self._mark_execution_blocked_best_effort(
                    work_item=work_item,
                    existing_work_item=promoted_work_item,
                )
                return self._fail_dashboard_update(
                    record=record,
                    dashboard_item_id=work_item.dashboard_item_id,
                    workflow_message=(
                        f"Selected dashboard item {work_item.dashboard_item_id} for remediation."
                    ),
                    dashboard_error_message=in_progress_result.error_message,
                )

        execution_result = ExecutionService(
            repo_root=self.repo_root,
            config=self.config,
        ).execute_with_context(
            selected_issue=remediation_work_item_to_execution_target(work_item),
            context=context,
            dry_run=active_dry_run,
            branch_name=build_remediation_branch_name(
                branch_prefix=self.config.branch_prefix,
                source=work_item.source_type,
                source_reference=work_item.source_ref,
                file_path=work_item.file_path,
                attempt_number=intake_result.selected_item.attempt_number,
            ),
        )
        change_request_url = execution_result.change_request_url
        change_request_action = execution_result.change_request_action
        record.branch_name = execution_result.branch_name
        record.commit_sha = execution_result.commit_sha

        if execution_result.failure is not None:
            self._mark_execution_blocked_best_effort(
                work_item=work_item,
                existing_work_item=promoted_work_item,
            )
            if live_dashboard_updates:
                failed_update = DashboardRemediationUpdater(self.dashboard_service).mark_failed(
                    project_id=project_id,
                    dashboard_item_id=work_item.dashboard_item_id,
                    run_id=run_id,
                    error_message=execution_result.failure.message,
                    retry_count=retry_count,
                    publication_retry=_publication_retry_from_execution(execution_result),
                )
                if failed_update.error_message is not None:
                    return self._fail_dashboard_update(
                        record=record,
                        dashboard_item_id=work_item.dashboard_item_id,
                        workflow_message=_with_dashboard_recovery_note(
                            execution_result.failure.message,
                            recovered_stale_item_ids=recovered_stale_item_ids,
                        ),
                        dashboard_error_message=failed_update.error_message,
                    )
            return self.run_state_service.dashboard.fail_item(
                record=record,
                dashboard_item_id=work_item.dashboard_item_id,
                error_message=_with_dashboard_recovery_note(
                    execution_result.failure.message,
                    recovered_stale_item_ids=recovered_stale_item_ids,
                ),
                failure=execution_result.failure,
            )

        if (
            execution_result.final_status is not None
            and execution_result.final_status.value == "rejected"
        ):
            self._mark_execution_dismissed_best_effort(
                work_item=work_item,
                existing_work_item=promoted_work_item,
            )
            if live_dashboard_updates:
                rejected_update = DashboardRemediationUpdater(self.dashboard_service).mark_rejected(
                    project_id=project_id,
                    dashboard_item_id=work_item.dashboard_item_id,
                    run_id=run_id,
                    rejection_reason=execution_result.status_message,
                )
                if rejected_update.error_message is not None:
                    return self._fail_dashboard_update(
                        record=record,
                        dashboard_item_id=work_item.dashboard_item_id,
                        workflow_message=_with_dashboard_recovery_note(
                            execution_result.status_message,
                            recovered_stale_item_ids=recovered_stale_item_ids,
                        ),
                        dashboard_error_message=rejected_update.error_message,
                    )
            return self.run_state_service.dashboard.reject_item(
                record=record,
                dashboard_item_id=work_item.dashboard_item_id,
                branch_name=execution_result.branch_name,
                message=_with_dashboard_recovery_note(
                    execution_result.status_message,
                    recovered_stale_item_ids=recovered_stale_item_ids,
                ),
            )

        if (
            live_dashboard_updates
            and change_request_url is not None
            and execution_result.commit_sha
        ):
            record.change_request_url = change_request_url
            change_request_opened_update = DashboardRemediationUpdater(
                self.dashboard_service
            ).mark_change_request_opened(
                project_id=project_id,
                dashboard_item_id=work_item.dashboard_item_id,
                run_id=run_id,
                branch_name=execution_result.branch_name or "",
                change_request_url=change_request_url,
                commit_sha=execution_result.commit_sha,
                retry_count=retry_count,
                retry_eligible=False,
                retry_block_reason=None,
            )
            if change_request_opened_update.error_message is not None:
                return self._fail_dashboard_update(
                    record=record,
                    dashboard_item_id=work_item.dashboard_item_id,
                    workflow_message=_with_dashboard_recovery_note(
                        "Remediation succeeded and created a change request, but the dashboard "
                        "state could not be updated.",
                        recovered_stale_item_ids=recovered_stale_item_ids,
                    ),
                    dashboard_error_message=change_request_opened_update.error_message,
                )

        if change_request_url is not None:
            self.run_state_service.dashboard.mark_change_request_created(
                record=record,
                dashboard_item_id=work_item.dashboard_item_id,
                branch_name=execution_result.branch_name,
                change_request_url=change_request_url,
            )
        elif live_dashboard_updates:
            self._mark_execution_completed_best_effort(
                work_item=work_item,
                existing_work_item=promoted_work_item,
            )

        self.run_state_service.dashboard.finish_success()
        return self.run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=_with_dashboard_recovery_note(
                (
                    f"Selected dashboard item {work_item.dashboard_item_id} in "
                    f"{work_item.file_path} ({work_item.rule_id}, {work_item.severity}). "
                    f"{execution_result.status_message}"
                ),
                recovered_stale_item_ids=recovered_stale_item_ids,
            ),
            dashboard_item_id=work_item.dashboard_item_id,
            branch_name=record.branch_name,
            commit_sha=record.commit_sha,
            change_request_url=change_request_url,
            change_request_action=change_request_action,
        )

    def _retry_recorded_publication(
        self,
        *,
        project_id: str,
        work_item: RemediationWorkItem,
        record: RunRecord,
        active_dry_run: bool,
        recovered_stale_item_ids: tuple[str, ...],
    ) -> RunSummary:
        """Retry verified publication without rerunning analysis or patch generation."""
        document = self.dashboard_service.load_or_create(project_id=project_id)
        dashboard_item = document.items_by_id().get(work_item.dashboard_item_id)
        if dashboard_item is None or dashboard_item.publication_retry is None:
            message = (
                "Recorded publication retry state is unavailable for "
                f"{work_item.dashboard_item_id}."
            )
            return self.run_state_service.dashboard.fail_item(
                record=record,
                dashboard_item_id=work_item.dashboard_item_id,
                error_message=message,
                failure=FailureDetails(stage=FailureStage.PUBLISH, message=message),
            )
        publication_retry = dashboard_item.publication_retry
        if active_dry_run:
            return self.run_state_service.build_summary(
                run_id=record.run_id,
                status=record.status,
                message=_with_dashboard_recovery_note(
                    "Dry-run would verify and retry recorded branch publication.",
                    recovered_stale_item_ids=recovered_stale_item_ids,
                ),
                dashboard_item_id=work_item.dashboard_item_id,
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
                selected_issue=remediation_work_item_to_execution_target(work_item),
                source_branch=publication_retry.branch_name,
                change_summary="Retrying publication for the existing remediation branch.",
            ),
        )
        if not result.succeeded or result.change_request is None:
            message = result.error_message or "Recorded branch publication retry failed."
            record.branch_name = publication_retry.branch_name
            record.commit_sha = publication_retry.commit_sha
            DashboardRemediationUpdater(self.dashboard_service).mark_failed(
                project_id=project_id,
                dashboard_item_id=work_item.dashboard_item_id,
                run_id=record.run_id,
                error_message=message,
                publication_retry=publication_retry,
            )
            return self.run_state_service.dashboard.fail_item(
                record=record,
                dashboard_item_id=work_item.dashboard_item_id,
                error_message=_with_dashboard_recovery_note(
                    message,
                    recovered_stale_item_ids=recovered_stale_item_ids,
                ),
                failure=FailureDetails(stage=FailureStage.PUBLISH, message=message),
            )
        update = DashboardRemediationUpdater(self.dashboard_service).mark_change_request_opened(
            project_id=project_id,
            dashboard_item_id=work_item.dashboard_item_id,
            run_id=record.run_id,
            branch_name=publication_retry.branch_name,
            change_request_url=result.change_request.web_url,
            change_request_number=result.change_request.iid,
            commit_sha=publication_retry.commit_sha,
            clear_publication_retry=True,
        )
        if update.error_message is not None:
            return self._fail_dashboard_update(
                record=record,
                dashboard_item_id=work_item.dashboard_item_id,
                workflow_message="Recorded branch publication retry succeeded.",
                dashboard_error_message=update.error_message,
            )
        self.run_state_service.dashboard.mark_change_request_created(
            record=record,
            dashboard_item_id=work_item.dashboard_item_id,
            branch_name=publication_retry.branch_name,
            change_request_url=result.change_request.web_url,
        )
        self.run_state_service.dashboard.finish_success()
        return self.run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=_with_dashboard_recovery_note(
                "Recorded branch publication retry completed.",
                recovered_stale_item_ids=recovered_stale_item_ids,
            ),
            dashboard_item_id=work_item.dashboard_item_id,
            branch_name=publication_retry.branch_name,
            commit_sha=publication_retry.commit_sha,
            change_request_url=result.change_request.web_url,
            change_request_action=result.action,
        )

    def _fail_dashboard_update(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        workflow_message: str,
        dashboard_error_message: str,
    ) -> RunSummary:
        """Return a failed run summary when a dashboard lifecycle write fails."""
        message = f"{workflow_message} Dashboard lifecycle update failed: {dashboard_error_message}"
        return self.run_state_service.dashboard.fail_item(
            record=record,
            dashboard_item_id=dashboard_item_id,
            error_message=message,
            failure=FailureDetails(
                stage=FailureStage.DASHBOARD_UPDATE,
                message=message,
            ),
        )

    def _remediation_control_plane_instance(self) -> RemediationControlPlane:
        """Return the remediation control plane, building defaults lazily."""
        if self._remediation_control_plane_override is not None:
            return self._remediation_control_plane_override
        if self._remediation_control_plane is None:
            self._remediation_control_plane = build_remediation_control_plane(self.config)
        return self._remediation_control_plane

    def _materialize_promoted_work_item_best_effort(
        self,
        *,
        work_item: RemediationWorkItem,
        promotion_context: RemediationWorkItemPromotionContext,
    ) -> WorkItemState | None:
        """Project promoted work-item state without blocking remediation execution."""
        try:
            return self._remediation_control_plane_instance().materialize_promoted_work_item(
                work_item=work_item,
                promotion_context=promotion_context,
            )
        except Exception:
            LOGGER.warning(
                "Remediation control-plane promotion materialization failed before execution",
                extra={"dashboard_item_id": work_item.dashboard_item_id},
                exc_info=True,
            )
            return None

    def _mark_execution_blocked_best_effort(
        self,
        *,
        work_item: RemediationWorkItem,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Project blocked work-item state without altering the primary failure result."""
        try:
            self._remediation_control_plane_instance().mark_execution_blocked(
                selected_issue=remediation_work_item_to_execution_target(work_item),
                existing_work_item=existing_work_item,
            )
        except Exception:
            LOGGER.warning(
                "Remediation control-plane blocked-state sync failed before publish",
                extra={"dashboard_item_id": work_item.dashboard_item_id},
                exc_info=True,
            )

    def _mark_execution_dismissed_best_effort(
        self,
        *,
        work_item: RemediationWorkItem,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Project dismissed work-item state without altering the primary rejection result."""
        try:
            self._remediation_control_plane_instance().mark_execution_dismissed(
                selected_issue=remediation_work_item_to_execution_target(work_item),
                existing_work_item=existing_work_item,
            )
        except Exception:
            LOGGER.warning(
                "Remediation control-plane dismissed-state sync failed after rejection",
                extra={"dashboard_item_id": work_item.dashboard_item_id},
                exc_info=True,
            )

    def _mark_execution_completed_best_effort(
        self,
        *,
        work_item: RemediationWorkItem,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Project completed work-item state without altering the primary success result."""
        try:
            self._remediation_control_plane_instance().mark_execution_completed(
                selected_issue=remediation_work_item_to_execution_target(work_item),
                existing_work_item=existing_work_item,
            )
        except Exception:
            LOGGER.warning(
                "Remediation control-plane completed-state sync failed after successful execution",
                extra={"dashboard_item_id": work_item.dashboard_item_id},
                exc_info=True,
            )


def _with_dashboard_recovery_note(
    message: str,
    *,
    recovered_stale_item_ids: tuple[str, ...],
) -> str:
    """Append one stale-recovery note to a dashboard remediation summary."""
    if not recovered_stale_item_ids:
        return message
    if len(recovered_stale_item_ids) == 1:
        recovery_note = (
            "Recovered stale in_progress dashboard item before remediation: "
            f"{recovered_stale_item_ids[0]}."
        )
    else:
        recovery_note = (
            "Recovered stale in_progress dashboard items before remediation: "
            f"{', '.join(recovered_stale_item_ids)}."
        )
    return f"{message} {recovery_note}"


def _publication_retry_from_execution(
    execution_result: object,
) -> PublicationRetryState | None:
    """Retain only a verified branch that failed while opening a change request."""
    failure = getattr(execution_result, "failure", None)
    branch_name = getattr(execution_result, "branch_name", None)
    commit_sha = getattr(execution_result, "commit_sha", None)
    if (
        failure is None
        or failure.stage != FailureStage.PUBLISH
        or not isinstance(branch_name, str)
        or not isinstance(commit_sha, str)
    ):
        return None
    return PublicationRetryState(
        branch_name=branch_name,
        commit_sha=commit_sha,
        reason="change_request_publish_failed",
    )
