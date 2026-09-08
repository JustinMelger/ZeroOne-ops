"""Execution workflow service.

This module coordinates the non-intake execution flow for one selected issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.analysis import (
    IssueContext,
    PatchProposal,
    RemediationIntent,
    SemanticSafetyAssessment,
    ValidationComparison,
)
from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import FailureDetails, FailureStage, RunStatus
from zeroone_ops.services.remediation.analysis_service import (
    AnalysisResult,
    AnalysisService,
)
from zeroone_ops.services.remediation.control_plane import RemediationControlPlane
from zeroone_ops.services.remediation.publication_request_builder import (
    RemediationPublicationRequestBuilder,
)
from zeroone_ops.services.remediation.publish_service import (
    PublishResult,
    PublishService,
)
from zeroone_ops.services.shared.approval import ApprovalService
from zeroone_ops.services.shared.branch_manager import (
    BranchManager,
    BranchManagerError,
)
from zeroone_ops.services.shared.runtime_workspace import RuntimeWorkspacePolicy
from zeroone_ops.services.shared.workspace_snapshot import WorkspaceSnapshotService
from zeroone_ops.utils.git import build_remediation_branch_name


@dataclass
class ExecutionResult:
    """Summarize execution of one selected issue."""

    analysis_result: AnalysisResult
    status_message: str
    failure: FailureDetails | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    change_request_url: str | None = None
    change_request_action: str | None = None
    published_change_request: ChangeRequestInfo | None = None
    publish_attempted: bool = False
    final_status: RunStatus | None = None
    terminal_rejection_stage: FailureStage | None = None


class ExecutionService:
    """Execute analysis, git, and publish flow for a selected issue.

    Args:
        repo_root: Repository root path.
        config: Loaded application configuration.
    """

    def __init__(
        self,
        repo_root: Path,
        config: AppConfig,
        *,
        remediation_control_plane: RemediationControlPlane | None = None,
    ) -> None:
        """Initialize the execution service.

        Args:
            repo_root: Repository root path.
            config: Loaded application configuration.
            remediation_control_plane: Optional provider-local lifecycle projection.
        """
        self.repo_root = repo_root
        self.config = config
        runtime_workspace_policy = RuntimeWorkspacePolicy.from_config(
            config=config,
            repo_root=repo_root,
        )
        self.analysis_service = AnalysisService(
            repo_root=repo_root,
            config=config,
            runtime_workspace_policy=runtime_workspace_policy,
        )
        self.approval_service = ApprovalService()
        self.branch_manager = BranchManager(
            repo_root,
            runtime_workspace_policy=runtime_workspace_policy,
        )
        self.workspace_snapshot_service = WorkspaceSnapshotService(repo_root)
        self.publish_service = PublishService(
            config=config,
            branch_manager=self.branch_manager,
            remediation_control_plane=remediation_control_plane,
        )

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
            except BranchManagerError as error:
                return ExecutionResult(
                    analysis_result=AnalysisResult(summary="Execution stopped before analysis."),
                    status_message=f"Branch preparation failed: {error}",
                    failure=FailureDetails(
                        stage=FailureStage.BRANCH_PREPARATION,
                        message=f"Branch preparation failed: {error}",
                    ),
                )

        def prepare_branch(patch: PatchProposal) -> FailureDetails | None:
            nonlocal branch_name
            try:
                branch_name = self._create_remediation_branch(
                    selected_issue=selected_issue,
                    remediation_intent=patch.remediation_intent,
                )
            except BranchManagerError as error:
                return FailureDetails(
                    stage=FailureStage.BRANCH_PREPARATION,
                    message=f"Branch preparation failed: {error}",
                )
            return None

        analysis_result = self.analysis_service.analyze_issue(
            selected_issue=selected_issue,
            dry_run=dry_run,
            pre_patch_handler=None if dry_run else prepare_branch,
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
        branch_name: str | None = None,
        attempt_number: int = 1,
    ) -> ExecutionResult:
        """Run the execution flow for one execution target with prebuilt context."""
        if not dry_run:
            try:
                self.branch_manager.ensure_ready()
                if branch_name is not None:
                    # Legacy dashboard callers retain their existing branch identity.
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

        def prepare_branch(patch: PatchProposal) -> FailureDetails | None:
            nonlocal branch_name
            if branch_name is not None:
                return None
            try:
                branch_name = self._create_remediation_branch(
                    selected_issue=selected_issue,
                    remediation_intent=patch.remediation_intent,
                    attempt_number=attempt_number,
                )
            except BranchManagerError as error:
                return FailureDetails(
                    stage=FailureStage.BRANCH_PREPARATION,
                    message=f"Branch preparation failed: {error}",
                )
            return None

        if branch_name is not None:
            # Keep the deprecated dashboard execution contract unchanged.
            analysis_result = self.analysis_service.analyze_issue_with_context(
                selected_issue=selected_issue,
                context=context,
                dry_run=dry_run,
            )
        else:
            analysis_result = self.analysis_service.analyze_issue_with_context(
                selected_issue=selected_issue,
                context=context,
                dry_run=dry_run,
                pre_patch_handler=None if dry_run else prepare_branch,
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
                terminal_rejection_stage=(
                    analysis_result.terminal_rejection_stage or FailureStage.ANALYSIS
                ),
            )
        if dry_run or not self._should_commit(analysis_result):
            return ExecutionResult(
                analysis_result=analysis_result,
                status_message=analysis_result.summary,
                branch_name=branch_name,
            )
        patch = analysis_result.patch
        if patch is None:
            return ExecutionResult(
                analysis_result=analysis_result,
                status_message="Execution could not continue because no patch was produced.",
                failure=FailureDetails(
                    stage=FailureStage.ANALYSIS,
                    message="Execution could not continue because no patch was produced.",
                ),
                branch_name=branch_name,
            )
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
                commit_message=RemediationPublicationRequestBuilder.build_commit_message(
                    selected_issue=selected_issue,
                    remediation_intent=patch.remediation_intent,
                ),
                change_request_title=patch.change_request_title,
            )
            if not approved:
                self._rollback_pre_commit(analysis_result)
                return ExecutionResult(
                    analysis_result=analysis_result,
                    status_message="Local approval rejected the proposed change.",
                    branch_name=branch_name,
                    final_status=RunStatus.REJECTED,
                    terminal_rejection_stage=FailureStage.APPROVAL,
                )

        try:
            commit_sha = self.branch_manager.commit_and_push(
                RemediationPublicationRequestBuilder.build_commit_message(
                    selected_issue=selected_issue,
                    remediation_intent=patch.remediation_intent,
                ),
                push=False,
                files_to_commit=patch.files_touched,
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

        publish_result = self._publish_branch_and_create_change_request(
            selected_issue=selected_issue,
            change_request_title=patch.change_request_title,
            change_request_description=patch.change_request_description,
            remediation_intent=patch.remediation_intent,
            validation_comparison=analysis_result.validation_comparison,
            semantic_safety=(
                None
                if analysis_result.semantic_safety is None
                else analysis_result.semantic_safety.assessment
            ),
            commit_sha=commit_sha,
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
            change_request_url=publish_result.change_request_url,
            change_request_action=publish_result.change_request_action,
            published_change_request=publish_result.published_change_request,
            publish_attempted=True,
        )

    def _create_remediation_branch(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        remediation_intent: RemediationIntent,
        attempt_number: int = 1,
    ) -> str:
        """Create the one intent-named branch after patch scope is known."""
        branch_name = build_remediation_branch_name(
            branch_prefix=f"{self.config.branch_prefix}/{remediation_intent}",
            source=selected_issue.source_type,
            source_reference=selected_issue.source_ref,
            file_path=selected_issue.file_path,
            attempt_number=attempt_number,
        )
        self.branch_manager.create_branch(branch_name)
        return branch_name

    def _should_commit(self, analysis_result: AnalysisResult) -> bool:
        """Check whether execution should continue to commit creation."""
        return (
            analysis_result.patch is not None
            and analysis_result.patch_applied
            and (
                analysis_result.validation_passed is True
                or (
                    analysis_result.validation_comparison is not None
                    and analysis_result.validation_comparison.allows_publication
                )
            )
        )

    def _publish_branch_and_create_change_request(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        change_request_title: str,
        change_request_description: str,
        remediation_intent: RemediationIntent,
        validation_comparison: ValidationComparison | None,
        semantic_safety: SemanticSafetyAssessment | None,
        commit_sha: str,
    ) -> PublishResult:
        """Delegate publish behavior to the dedicated publish service."""
        return self.publish_service.publish(
            selected_issue=selected_issue,
            change_request_title=change_request_title,
            change_request_description=change_request_description,
            remediation_intent=remediation_intent,
            validation_comparison=validation_comparison,
            semantic_safety=semantic_safety,
            commit_sha=commit_sha,
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
