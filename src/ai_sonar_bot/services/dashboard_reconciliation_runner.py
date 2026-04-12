"""Dashboard reconciliation workflow runner."""

from __future__ import annotations

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.dashboard import DashboardItem
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
        config: AppConfig,
        dashboard_service: DashboardService,
        review_client: GitLabReviewClient,
        run_state_service: RunStateService,
    ) -> None:
        """Initialize the reconciliation workflow runner."""
        self.config = config
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
        selected_items = self._selected_items(intake_result)
        if not selected_items:
            return self.run_state_service.finish_no_issue(
                record=record,
                message=intake_result.message,
                issue_count=intake_result.item_count,
            )

        first_item = selected_items[0]
        record.dashboard_item_id = first_item.id
        record.branch_name = first_item.branch_name
        record.commit_sha = first_item.commit_sha
        record.mr_url = first_item.merge_request_url
        record.updated_at = utc_now()

        if active_dry_run:
            record.status = RunStatus.SELECTED
            self.run_state_service.state_store.save(self.run_state_service.state)
            return self.run_state_service.build_summary(
                run_id=record.run_id,
                status=record.status,
                message=self._build_dry_run_message(
                    project_id=project_id,
                    selected_items=selected_items,
                ),
                dashboard_item_id=first_item.id,
                branch_name=first_item.branch_name,
                commit_sha=first_item.commit_sha,
                mr_url=first_item.merge_request_url,
            )

        return self._run_live(
            project_id=project_id,
            run_id=run_id,
            record=record,
            selected_items=selected_items,
        )

    def _selected_items(self, intake_result: object) -> list[DashboardItem]:
        """Return selected reconciliation items from old or new intake results."""
        selected_items = getattr(intake_result, "selected_items", None)
        if selected_items is not None:
            return list(selected_items)
        selected_item = getattr(intake_result, "selected_item", None)
        if selected_item is None:
            return []
        return [selected_item]

    def _build_dry_run_message(
        self,
        *,
        project_id: str,
        selected_items: list[DashboardItem],
    ) -> str:
        """Build one dry-run message for the selected reconciliation batch."""
        decisions = [
            DashboardReconciliationService(self.review_client).decide(
                project_id=project_id,
                item=item,
            )
            for item in selected_items
        ]
        decision_parts = [
            f"{item.id}: {decision.message}"
            for item, decision in zip(selected_items, decisions, strict=True)
        ]
        item_label = "item" if len(selected_items) == 1 else "items"
        return (
            f"Dry-run would reconcile {len(selected_items)} dashboard {item_label}: "
            + "; ".join(decision_parts)
        )

    def _run_live(
        self,
        *,
        project_id: str,
        run_id: str,
        record: RunRecord,
        selected_items: list[DashboardItem],
    ) -> RunSummary:
        """Run reconciliation for the selected dashboard items."""
        decision_service = DashboardReconciliationService(
            self.review_client,
            max_review_feedback_retries=self.config.review.max_review_feedback_retries,
        )
        updater = DashboardRemediationUpdater(self.dashboard_service)
        noop_count = 0
        reconciled_count = 0
        reopened_count = 0
        done_count = 0
        failed_count = 0
        decision_parts: list[str] = []
        failed_parts: list[str] = []

        for item in selected_items:
            decision = decision_service.decide(project_id=project_id, item=item)
            record.dashboard_item_id = item.id
            record.branch_name = item.branch_name
            record.commit_sha = item.commit_sha
            record.mr_url = item.merge_request_url
            record.updated_at = utc_now()
            decision_parts.append(f"{item.id}: {decision.message}")

            if decision.action == "noop":
                noop_count += 1
                continue

            if decision.action == "done":
                update_result = updater.mark_done(
                    project_id=project_id,
                    dashboard_item_id=item.id,
                    run_id=run_id,
                    summary=decision.message,
                    retry_count=item.retry_count or 0,
                    retry_eligible=decision.retry_eligible,
                    retry_block_reason=decision.retry_block_reason,
                )
                if update_result.error_message is not None:
                    return self._fail_dashboard_update(
                        record=record,
                        dashboard_item_id=item.id,
                        workflow_message=decision.message,
                        dashboard_error_message=update_result.error_message,
                    )
                self.run_state_service.dashboard.mark_done(
                    record=record,
                    dashboard_item_id=item.id,
                    branch_name=item.branch_name,
                    commit_sha=item.commit_sha,
                    mr_url=item.merge_request_url,
                )
                reconciled_count += 1
                done_count += 1
                continue

            if decision.action == "open":
                update_result = updater.mark_open(
                    project_id=project_id,
                    dashboard_item_id=item.id,
                    run_id=run_id,
                    summary=decision.message,
                    retry_count=item.retry_count or 0,
                    retry_eligible=decision.retry_eligible,
                    retry_block_reason=decision.retry_block_reason,
                )
                if update_result.error_message is not None:
                    return self._fail_dashboard_update(
                        record=record,
                        dashboard_item_id=item.id,
                        workflow_message=decision.message,
                        dashboard_error_message=update_result.error_message,
                    )
                self.run_state_service.dashboard.mark_reopened(
                    record=record,
                    dashboard_item_id=item.id,
                    branch_name=item.branch_name,
                    commit_sha=item.commit_sha,
                    mr_url=item.merge_request_url,
                )
                reconciled_count += 1
                reopened_count += 1
                continue

            update_result = updater.mark_failed(
                project_id=project_id,
                dashboard_item_id=item.id,
                run_id=run_id,
                error_message=decision.message,
                retry_count=item.retry_count or 0,
                retry_eligible=decision.retry_eligible,
                retry_block_reason=decision.retry_block_reason,
            )
            if update_result.error_message is not None:
                return self._fail_dashboard_update(
                    record=record,
                    dashboard_item_id=item.id,
                    workflow_message=decision.message,
                    dashboard_error_message=update_result.error_message,
                )
            self.run_state_service.dashboard.mark_failed(
                record=record,
                dashboard_item_id=item.id,
                error_message=decision.message,
                branch_name=item.branch_name,
                commit_sha=item.commit_sha,
                mr_url=item.merge_request_url,
            )
            failed_parts.append(f"{item.id} ({decision.message})")
            reconciled_count += 1
            failed_count += 1

        if reconciled_count == 0:
            record.status = RunStatus.NO_ISSUE
        else:
            record.status = RunStatus.RECONCILED
        self.run_state_service.dashboard.finish_success()
        return self.run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=self._build_live_message(
                selected_count=len(selected_items),
                reconciled_count=reconciled_count,
                done_count=done_count,
                reopened_count=reopened_count,
                failed_count=failed_count,
                noop_count=noop_count,
                decision_parts=decision_parts,
                failed_parts=failed_parts,
            ),
            dashboard_item_id=record.dashboard_item_id,
            branch_name=record.branch_name,
            commit_sha=record.commit_sha,
            mr_url=record.mr_url,
        )

    def _build_live_message(
        self,
        *,
        selected_count: int,
        reconciled_count: int,
        done_count: int,
        reopened_count: int,
        failed_count: int,
        noop_count: int,
        decision_parts: list[str],
        failed_parts: list[str],
    ) -> str:
        """Build one reconciliation summary for a live batch."""
        outcome = (
            f"Reconciliation checked {selected_count} dashboard items: "
            f"{done_count} marked done, {reopened_count} reopened, "
            f"{failed_count} marked failed, {noop_count} still open."
        )
        if reconciled_count == 0:
            outcome = (
                f"Reconciliation checked {selected_count} dashboard items and found "
                f"{noop_count} still-open merge requests."
            )
        message = f"{outcome} " + "; ".join(decision_parts)
        if failed_parts:
            message += " Failed items: " + "; ".join(failed_parts)
        return message

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
