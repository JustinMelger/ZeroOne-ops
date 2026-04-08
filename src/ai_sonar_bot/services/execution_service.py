"""Execution workflow service.

This module coordinates the non-intake execution flow for one selected issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.analysis import IssueContext, ValidationResult
from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.remediation import RemediationExecutionTarget
from ai_sonar_bot.models.state import FailureDetails, FailureStage, RunStatus
from ai_sonar_bot.services.analysis_service import AnalysisResult, AnalysisService
from ai_sonar_bot.services.approval import ApprovalService
from ai_sonar_bot.services.branch_manager import BranchManager, BranchManagerError
from ai_sonar_bot.services.publish_service import PublishResult, PublishService
from ai_sonar_bot.services.workspace_snapshot import WorkspaceSnapshotService


@dataclass
class ExecutionResult:
    """Summarize execution of one selected issue."""

    analysis_result: AnalysisResult
    status_message: str
    failure: FailureDetails | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    mr_url: str | None = None
    mr_action: str | None = None
    publish_attempted: bool = False
    final_status: RunStatus | None = None


class ExecutionService:
    """Execute analysis, git, and publish flow for a selected issue.

    Args:
        repo_root: Repository root path.
        config: Loaded application configuration.
    """

    def __init__(self, repo_root: Path, config: AppConfig) -> None:
        """Initialize the execution service.

        Args:
            repo_root: Repository root path.
            config: Loaded application configuration.
        """
        self.repo_root = repo_root
        self.config = config
        self.analysis_service = AnalysisService(repo_root=repo_root, config=config)
        self.approval_service = ApprovalService()
        self.branch_manager = BranchManager(repo_root)
        self.workspace_snapshot_service = WorkspaceSnapshotService(repo_root)
        self.publish_service = PublishService(config=config, branch_manager=self.branch_manager)

    def execute(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        dry_run: bool,
    ) -> ExecutionResult:
        """Run the execution flow for a selected execution target.

        Args:
            selected_issue: Selected remediation execution target.
            dry_run: Whether to run in dry-run mode.

        Returns:
            Structured execution result.
        """
        branch_name: str | None = None
        if not dry_run:
            try:
                self.branch_manager.ensure_ready()
                branch_name = self.branch_manager.build_branch_name(
                    branch_prefix=self.config.branch_prefix,
                    issue_key=selected_issue.source_ref,
                    file_path=selected_issue.file_path,
                )
                self.branch_manager.create_branch(branch_name)
            except BranchManagerError as error:
                return ExecutionResult(
                    analysis_result=AnalysisResult(summary="Execution stopped before analysis."),
                    status_message=f"Branch preparation failed: {error}",
                    failure=FailureDetails(
                        stage=FailureStage.BRANCH_PREPARATION,
                        message=f"Branch preparation failed: {error}",
                    ),
                )

        analysis_result = self.analysis_service.analyze_issue(
            selected_issue=selected_issue,
            dry_run=dry_run,
        )
        return self._continue_execution(
            selected_issue=selected_issue,
            analysis_result=analysis_result,
            dry_run=dry_run,
            branch_name=branch_name,
        )

    def execute_with_context(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        context: IssueContext,
        dry_run: bool,
    ) -> ExecutionResult:
        """Run the execution flow for one execution target with prebuilt context."""
        branch_name: str | None = None
        if not dry_run:
            try:
                self.branch_manager.ensure_ready()
                branch_name = self.branch_manager.build_branch_name(
                    branch_prefix=self.config.branch_prefix,
                    issue_key=selected_issue.source_ref,
                    file_path=selected_issue.file_path,
                )
                self.branch_manager.create_branch(branch_name)
            except BranchManagerError as error:
                return ExecutionResult(
                    analysis_result=AnalysisResult(summary="Execution stopped before analysis."),
                    status_message=f"Branch preparation failed: {error}",
                    failure=FailureDetails(
                        stage=FailureStage.BRANCH_PREPARATION,
                        message=f"Branch preparation failed: {error}",
                    ),
                )

        analysis_result = self.analysis_service.analyze_issue_with_context(
            selected_issue=selected_issue,
            context=context,
            dry_run=dry_run,
        )
        return self._continue_execution(
            selected_issue=selected_issue,
            analysis_result=analysis_result,
            dry_run=dry_run,
            branch_name=branch_name,
        )

    def _continue_execution(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        analysis_result: AnalysisResult,
        dry_run: bool,
        branch_name: str | None,
    ) -> ExecutionResult:
        """Continue execution after analysis has completed."""
        if analysis_result.failure is not None:
            return ExecutionResult(
                analysis_result=analysis_result,
                status_message=analysis_result.failure.message,
                failure=analysis_result.failure,
                branch_name=branch_name,
            )
        if analysis_result.patch is None and analysis_result.validation_passed is False:
            return ExecutionResult(
                analysis_result=analysis_result,
                status_message=analysis_result.summary,
                branch_name=branch_name,
                final_status=RunStatus.REJECTED,
            )
        if dry_run or not self._should_commit(analysis_result):
            return ExecutionResult(
                analysis_result=analysis_result,
                status_message=analysis_result.summary,
                branch_name=branch_name,
            )
        patch = analysis_result.patch
        assert patch is not None
        if self.config.requires_local_approval():
            validation_result = analysis_result.validation_result
            if validation_result is None:
                return ExecutionResult(
                    analysis_result=analysis_result,
                    status_message=(
                        "Local approval could not run because validation did not execute."
                    ),
                    failure=FailureDetails(
                        stage=FailureStage.APPROVAL,
                        message=(
                            "Local approval could not run because validation did not execute."
                        ),
                    ),
                    branch_name=branch_name,
                )
            approved = self.approval_service.request(
                issue=selected_issue,
                changed_files=patch.files_touched,
                validation=validation_result,
                commit_message=patch.commit_message,
                mr_title=patch.mr_title,
            )
            if not approved:
                self._rollback_pre_commit(analysis_result)
                return ExecutionResult(
                    analysis_result=analysis_result,
                    status_message="Local approval rejected the proposed change.",
                    branch_name=branch_name,
                    final_status=RunStatus.REJECTED,
                )

        try:
            commit_sha = self.branch_manager.commit_and_push(
                patch.commit_message,
                push=False,
            )
        except BranchManagerError as error:
            self._rollback_pre_commit(analysis_result)
            return ExecutionResult(
                analysis_result=analysis_result,
                status_message=f"Commit failed: {error}",
                failure=FailureDetails(
                    stage=FailureStage.COMMIT,
                    message=f"Commit failed: {error}",
                ),
                branch_name=branch_name,
            )

        if self.config.execution_mode != "ci":
            return ExecutionResult(
                analysis_result=analysis_result,
                status_message=analysis_result.summary,
                branch_name=branch_name,
                commit_sha=commit_sha,
            )

        publish_result = self._publish_branch_and_create_mr(
            selected_issue=selected_issue,
            validation_result=analysis_result.validation_result,
            branch_name=branch_name or "",
            mr_title=patch.mr_title,
            mr_description=patch.mr_description,
        )
        if publish_result.error_message is not None:
            return ExecutionResult(
                analysis_result=analysis_result,
                status_message=publish_result.error_message,
                failure=FailureDetails(
                    stage=FailureStage.PUBLISH,
                    message=publish_result.error_message,
                ),
                branch_name=branch_name,
                commit_sha=commit_sha,
                publish_attempted=True,
            )

        return ExecutionResult(
            analysis_result=analysis_result,
            status_message=analysis_result.summary,
            branch_name=branch_name,
            commit_sha=commit_sha,
            mr_url=publish_result.mr_url,
            mr_action=publish_result.mr_action,
            publish_attempted=True,
        )

    def _should_commit(self, analysis_result: AnalysisResult) -> bool:
        """Check whether execution should continue to commit creation."""
        return (
            analysis_result.patch is not None
            and analysis_result.patch_applied
            and analysis_result.validation_passed is True
        )

    def _publish_branch_and_create_mr(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        validation_result: ValidationResult | None,
        branch_name: str,
        mr_title: str,
        mr_description: str,
    ) -> PublishResult:
        """Delegate publish behavior to the dedicated publish service."""
        return self.publish_service.publish(
            selected_issue=selected_issue,
            validation_result=validation_result,
            branch_name=branch_name,
            mr_title=mr_title,
            mr_description=mr_description,
        )

    def _rollback_pre_commit(self, analysis_result: AnalysisResult) -> None:
        """Restore the pre-apply workspace state before commit succeeds.

        Args:
            analysis_result: Analysis result containing the original snapshot.
        """
        snapshot = analysis_result.workspace_snapshot
        if snapshot is None:
            return
        self.branch_manager.reset_index()
        self.workspace_snapshot_service.restore(snapshot)
