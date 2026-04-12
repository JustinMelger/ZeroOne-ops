"""Dashboard remediation workflow runner."""

from __future__ import annotations

from pathlib import Path

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.state import AppState, FailureDetails, FailureStage, RunRecord
from ai_sonar_bot.services.dashboard_item_intake import DashboardItemIntakeService
from ai_sonar_bot.services.dashboard_item_normalizer import DashboardItemNormalizer
from ai_sonar_bot.services.dashboard_remediation_updater import DashboardRemediationUpdater
from ai_sonar_bot.services.dashboard_service import DashboardService
from ai_sonar_bot.services.execution_service import ExecutionService
from ai_sonar_bot.services.remediation_context_builder import RemediationContextBuilder
from ai_sonar_bot.services.remediation_execution_adapter import (
    remediation_work_item_to_execution_target,
)
from ai_sonar_bot.services.run_state_service import RunStateService, RunSummary


class DashboardRemediationRunner:
    """Run the dashboard remediation workflow with injected dependencies."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        dashboard_service: DashboardService,
        run_state_service: RunStateService,
    ) -> None:
        """Initialize the remediation workflow runner."""
        self.repo_root = repo_root
        self.config = config
        self.dashboard_service = dashboard_service
        self.run_state_service = run_state_service

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
        context = RemediationContextBuilder(self.repo_root, self.config).build(work_item)
        if context is None:
            message = f"Context unavailable for dashboard item {work_item.dashboard_item_id}."
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

        live_dashboard_updates = not active_dry_run and self.config.execution_mode == "ci"
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
        )
        record.branch_name = execution_result.branch_name
        record.commit_sha = execution_result.commit_sha

        if execution_result.failure is not None:
            if live_dashboard_updates:
                failed_update = DashboardRemediationUpdater(self.dashboard_service).mark_failed(
                    project_id=project_id,
                    dashboard_item_id=work_item.dashboard_item_id,
                    run_id=run_id,
                    error_message=execution_result.failure.message,
                    retry_count=retry_count,
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
            and execution_result.mr_url is not None
            and execution_result.commit_sha
        ):
            record.mr_url = execution_result.mr_url
            mr_opened_update = DashboardRemediationUpdater(self.dashboard_service).mark_mr_opened(
                project_id=project_id,
                dashboard_item_id=work_item.dashboard_item_id,
                run_id=run_id,
                branch_name=execution_result.branch_name or "",
                merge_request_url=execution_result.mr_url,
                commit_sha=execution_result.commit_sha,
                retry_count=retry_count,
                retry_eligible=False,
                retry_block_reason=None,
            )
            if mr_opened_update.error_message is not None:
                return self._fail_dashboard_update(
                    record=record,
                    dashboard_item_id=work_item.dashboard_item_id,
                    workflow_message=_with_dashboard_recovery_note(
                        "Remediation succeeded and created a merge request, but the dashboard "
                        "state could not be updated.",
                        recovered_stale_item_ids=recovered_stale_item_ids,
                    ),
                    dashboard_error_message=mr_opened_update.error_message,
                )

        if execution_result.mr_url is not None:
            self.run_state_service.dashboard.mark_mr_created(
                record=record,
                dashboard_item_id=work_item.dashboard_item_id,
                branch_name=execution_result.branch_name,
                mr_url=execution_result.mr_url,
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
            mr_url=execution_result.mr_url,
            mr_action=execution_result.mr_action,
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
