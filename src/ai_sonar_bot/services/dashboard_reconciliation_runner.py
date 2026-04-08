"""Dashboard reconciliation workflow runner."""

from __future__ import annotations

from ai_sonar_bot.models.state import FailureDetails, FailureStage, RunRecord, RunStatus, utc_now
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient
from ai_sonar_bot.services.dashboard_reconciliation_intake import (
    DashboardReconciliationIntakeService,
)
from ai_sonar_bot.services.dashboard_reconciliation_service import (
    DashboardReconciliationService,
)
from ai_sonar_bot.services.dashboard_remediation_updater import DashboardRemediationUpdater
from ai_sonar_bot.services.dashboard_service import DashboardService
from ai_sonar_bot.services.run_state_service import RunStateService, RunSummary


class DashboardReconciliationRunner:
    """Run the dashboard reconciliation workflow with injected dependencies."""

    def __init__(
        self,
        *,
        dashboard_service: DashboardService,
        review_client: GitLabReviewClient,
        run_state_service: RunStateService,
    ) -> None:
        """Initialize the reconciliation workflow runner."""
        self.dashboard_service = dashboard_service
        self.review_client = review_client
        self.run_state_service = run_state_service

    def run(
        self,
        *,
        project_id: str,
        run_id: str,
        record: RunRecord,
        active_dry_run: bool,
        execution_mode: str,
    ) -> RunSummary:
        """Run one reconciliation workflow."""
        if not active_dry_run and execution_mode != "ci":
            message = (
                "Dashboard reconciliation live execution is only supported in CI mode. "
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

        intake_result = DashboardReconciliationIntakeService(
            dashboard_service=self.dashboard_service,
        ).select_item(project_id=project_id)
        if intake_result.selected_item is None:
            return self.run_state_service.finish_no_issue(
                record=record,
                message=intake_result.message,
                issue_count=intake_result.item_count,
            )

        selected_item = intake_result.selected_item
        decision = DashboardReconciliationService(self.review_client).decide(
            project_id=project_id,
            item=selected_item,
        )
        record.dashboard_item_id = selected_item.id
        record.branch_name = selected_item.branch_name
        record.commit_sha = selected_item.commit_sha
        record.mr_url = selected_item.merge_request_url
        record.updated_at = utc_now()

        if active_dry_run:
            record.status = RunStatus.SELECTED
            self.run_state_service.state_store.save(self.run_state_service.state)
            return self.run_state_service.build_summary(
                run_id=record.run_id,
                status=record.status,
                message=(
                    f"Dry-run would reconcile dashboard item {selected_item.id}: "
                    f"{decision.message}"
                ),
                dashboard_item_id=selected_item.id,
                branch_name=selected_item.branch_name,
                commit_sha=selected_item.commit_sha,
                mr_url=selected_item.merge_request_url,
            )

        if decision.action == "noop":
            record.status = RunStatus.NO_ISSUE
            self.run_state_service.state_store.save(self.run_state_service.state)
            return self.run_state_service.build_summary(
                run_id=record.run_id,
                status=record.status,
                message=decision.message,
                dashboard_item_id=selected_item.id,
                branch_name=selected_item.branch_name,
                commit_sha=selected_item.commit_sha,
                mr_url=selected_item.merge_request_url,
            )

        updater = DashboardRemediationUpdater(self.dashboard_service)
        if decision.action == "done":
            update_result = updater.mark_done(
                project_id=project_id,
                dashboard_item_id=selected_item.id,
                run_id=run_id,
                summary=decision.message,
            )
            if update_result.error_message is not None:
                return self._fail_dashboard_update(
                    record=record,
                    dashboard_item_id=selected_item.id,
                    workflow_message=decision.message,
                    dashboard_error_message=update_result.error_message,
                )
            self.run_state_service.mark_dashboard_done(
                record=record,
                dashboard_item_id=selected_item.id,
                branch_name=selected_item.branch_name,
                commit_sha=selected_item.commit_sha,
                mr_url=selected_item.merge_request_url,
            )
            record.status = RunStatus.RECONCILED
            self.run_state_service.finish_success(record=record)
            return self.run_state_service.build_summary(
                run_id=record.run_id,
                status=record.status,
                message=decision.message,
                dashboard_item_id=selected_item.id,
                branch_name=selected_item.branch_name,
                commit_sha=selected_item.commit_sha,
                mr_url=selected_item.merge_request_url,
            )

        if decision.action == "open":
            update_result = updater.mark_open(
                project_id=project_id,
                dashboard_item_id=selected_item.id,
                run_id=run_id,
                summary=decision.message,
            )
            if update_result.error_message is not None:
                return self._fail_dashboard_update(
                    record=record,
                    dashboard_item_id=selected_item.id,
                    workflow_message=decision.message,
                    dashboard_error_message=update_result.error_message,
                )
            self.run_state_service.mark_dashboard_reopened(
                record=record,
                dashboard_item_id=selected_item.id,
                branch_name=selected_item.branch_name,
                commit_sha=selected_item.commit_sha,
                mr_url=selected_item.merge_request_url,
            )
            record.status = RunStatus.RECONCILED
            self.run_state_service.finish_success(record=record)
            return self.run_state_service.build_summary(
                run_id=record.run_id,
                status=record.status,
                message=decision.message,
                dashboard_item_id=selected_item.id,
                branch_name=selected_item.branch_name,
                commit_sha=selected_item.commit_sha,
                mr_url=selected_item.merge_request_url,
            )

        return self.run_state_service.fail_dashboard_item(
            record=record,
            dashboard_item_id=selected_item.id,
            error_message=decision.message,
            failure=FailureDetails(
                stage=FailureStage.RECONCILIATION,
                message=decision.message,
            ),
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
        return self.run_state_service.fail_dashboard_item(
            record=record,
            dashboard_item_id=dashboard_item_id,
            error_message=message,
            failure=FailureDetails(
                stage=FailureStage.DASHBOARD_UPDATE,
                message=message,
            ),
        )
