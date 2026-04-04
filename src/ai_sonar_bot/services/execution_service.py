"""Execution workflow service.

This module coordinates the non-intake execution flow for one selected issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import FailureDetails, FailureStage, RunStatus
from ai_sonar_bot.providers.gitlab_client import GitLabClient, GitLabClientError
from ai_sonar_bot.services.analysis_service import AnalysisResult, AnalysisService
from ai_sonar_bot.services.approval import ApprovalService
from ai_sonar_bot.services.branch_manager import BranchManager, BranchManagerError
from ai_sonar_bot.services.mr_service import MergeRequestService
from ai_sonar_bot.services.workspace_snapshot import WorkspaceSnapshotService
from ai_sonar_bot.settings import load_gitlab_connection_config


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


@dataclass
class PublishResult:
    """Summarize remote publish and merge request creation."""

    branch_name: str | None = None
    mr_url: str | None = None
    mr_action: str | None = None
    error_message: str | None = None


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

    def execute(self, *, selected_issue: SonarIssue, dry_run: bool) -> ExecutionResult:
        """Run the execution flow for a selected issue.

        Args:
            selected_issue: Selected SonarQube issue.
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
                    issue_key=selected_issue.key,
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
        if analysis_result.failure is not None:
            return ExecutionResult(
                analysis_result=analysis_result,
                status_message=analysis_result.failure.message,
                failure=analysis_result.failure,
                branch_name=branch_name,
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
            analysis_result=analysis_result,
            branch_name=branch_name or "",
            mr_title=patch.mr_title,
            mr_description=patch.mr_description,
            target_branch=self.config.gitlab.target_branch,
            labels=self.config.gitlab.labels,
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
        selected_issue: SonarIssue,
        analysis_result: AnalysisResult,
        branch_name: str,
        mr_title: str,
        mr_description: str,
        target_branch: str,
        labels: list[str],
    ) -> PublishResult:
        """Push the current branch and create or reuse a GitLab merge request."""
        try:
            gitlab_config = load_gitlab_connection_config()
            pushed_branch = self.branch_manager.push_current_branch()
            merge_request_service = MergeRequestService(GitLabClient(gitlab_config))
            existing_mr = merge_request_service.find_open(
                project_id=gitlab_config.project_id,
                source_branch=pushed_branch,
                target_branch=target_branch,
            )
            if existing_mr is not None:
                return PublishResult(
                    branch_name=pushed_branch,
                    mr_url=existing_mr.web_url,
                    mr_action="reused",
                )
            created_mr = merge_request_service.create(
                project_id=gitlab_config.project_id,
                source_branch=branch_name,
                target_branch=target_branch,
                title=mr_title,
                description=self._build_mr_description(
                    selected_issue=selected_issue,
                    analysis_result=analysis_result,
                    change_summary=mr_description,
                ),
                labels=labels,
            )
        except (BranchManagerError, GitLabClientError, RuntimeError) as error:
            return PublishResult(error_message=f"Publish failed: {error}")
        return PublishResult(
            branch_name=branch_name,
            mr_url=created_mr.web_url,
            mr_action="created",
        )

    def _build_mr_description(
        self,
        *,
        selected_issue: SonarIssue,
        analysis_result: AnalysisResult,
        change_summary: str,
    ) -> str:
        """Build a deterministic merge request description.

        Args:
            selected_issue: Selected SonarQube issue for this run.
            analysis_result: Analysis and validation outcome for the issue.
            change_summary: Short change summary from the generated patch metadata.

        Returns:
            Deterministic merge request description text.
        """
        issue_line = str(selected_issue.line) if selected_issue.line is not None else "n/a"
        validation_summary = (
            analysis_result.validation_result.summary
            if analysis_result.validation_result is not None
            else "Validation did not run."
        )
        return "\n".join(
            [
                "## Summary",
                change_summary,
                "",
                "## SonarQube",
                f"- Issue key: `{selected_issue.key}`",
                f"- Rule: `{selected_issue.rule}`",
                f"- Severity: `{selected_issue.severity}`",
                f"- Type: `{selected_issue.type}`",
                f"- File: `{selected_issue.file_path}`",
                f"- Line: `{issue_line}`",
                f"- Message: {selected_issue.message}",
                "",
                "## Validation",
                f"- {validation_summary}",
                "",
                "## Notes",
                "- Diff was rendered by the bot from a structured edit proposal.",
            ]
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
