"""GitHub-local remediation orchestration over shared execution services."""

from __future__ import annotations

import logging
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import FailureDetails, FailureStage, RunRecord, RunStatus
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.work_items.github_remediation_intake_service import (
    GitHubRemediationIntakeService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.remediation.control_plane import (
    RemediationControlPlane,
    build_remediation_control_plane,
)
from zeroone_ops.services.remediation.execution_service import ExecutionService
from zeroone_ops.services.remediation.remediation_context_builder import (
    RemediationContextBuilder,
)
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary

LOGGER = logging.getLogger(__name__)


class GitHubRemediationRunner:
    """Execute one selected GitHub work item through the shared remediation core."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        repository_id: str,
        work_item_service: GitHubWorkItemService,
        run_state_service: RunStateService,
        execution_service: ExecutionService | None = None,
        remediation_control_plane: RemediationControlPlane | None = None,
    ) -> None:
        """Initialize the GitHub-local remediation runner."""
        self.repo_root = repo_root
        self.config = config
        self.repository_id = repository_id
        self.work_item_service = work_item_service
        self.run_state_service = run_state_service
        self.execution_service = execution_service or ExecutionService(
            repo_root=repo_root,
            config=config,
        )
        self.remediation_control_plane = (
            remediation_control_plane
            or build_remediation_control_plane(
                config,
                github_work_item_service=work_item_service,
                github_repository_id=repository_id,
            )
        )

    def run(self, *, record: RunRecord, active_dry_run: bool) -> RunSummary:
        """Select, execute, and project one GitHub remediation work item."""
        if not active_dry_run and self.config.execution_mode != "ci":
            message = (
                "GitHub remediation live execution is only supported in CI mode. "
                "Use --dry-run locally."
            )
            return self.run_state_service.fail_run(
                record=record,
                error_message=message,
                failure=FailureDetails(stage=FailureStage.ISSUE_INTAKE, message=message),
            )

        intake_result = GitHubRemediationIntakeService(
            work_item_service=self.work_item_service
        ).select_and_claim(
            repository_id=self.repository_id,
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

        context = RemediationContextBuilder(self.repo_root, self.config).build(selected_target)
        if context is None:
            message = f"Context unavailable for GitHub work item {selected_target.item_id}."
            self._mark_blocked_best_effort(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                active_dry_run=active_dry_run,
            )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.FAILED,
                message=message,
                failure=FailureDetails(stage=FailureStage.ISSUE_INTAKE, message=message),
            )

        execution_result = self.execution_service.execute_with_context(
            selected_issue=selected_target,
            context=context,
            dry_run=active_dry_run,
        )
        if execution_result.failure is not None:
            self._mark_blocked_best_effort(
                selected_target=selected_target,
                claimed_work_item=claimed_work_item,
                active_dry_run=active_dry_run,
            )
            return self.run_state_service.finish_work_item(
                record=record,
                work_item_id=selected_target.item_id,
                status=RunStatus.FAILED,
                message=execution_result.failure.message,
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
    ) -> None:
        """Project an execution failure without replacing the primary outcome."""
        if active_dry_run:
            return
        try:
            self.remediation_control_plane.mark_execution_blocked(
                selected_issue=selected_target,
                existing_work_item=claimed_work_item,
            )
        except Exception:
            LOGGER.warning("GitHub work-item blocked-state projection failed", exc_info=True)

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
            LOGGER.warning("GitHub work-item dismissed-state projection failed", exc_info=True)

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
            LOGGER.warning("GitHub work-item completed-state projection failed", exc_info=True)
