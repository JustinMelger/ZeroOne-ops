"""Recovery workflow composition for GitHub and GitLab."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from zeroone_ops.models.config import AppConfig, GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.state import AppState, FailureDetails, FailureStage, RunStatus
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.services.control_plane.overview.github_operational_summary_service import (
    GitHubOperationalSummaryPublishResult,
)
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_service import (
    GitLabOperationalSummaryPublishResult,
)
from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    FindingSyncObservation,
)
from zeroone_ops.services.control_plane.policy.github_policy_issue_service import (
    GitHubPolicyIssueService,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_service import (
    GitLabPolicyIssueService,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_runner import (
    GitHubWorkItemRecoveryRunner,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_recovery_runner import (
    GitLabWorkItemRecoveryRunner,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_recovery_service import (
    GitLabWorkItemRecoveryService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.dashboard.dashboard_policy_view_builder import (
    DashboardPolicyViewBuilder,
)
from zeroone_ops.services.dashboard.dashboard_recovery_runner import (
    DashboardRecoveryRunner,
)
from zeroone_ops.services.dashboard.dashboard_recovery_service import DashboardRecoveryService
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary
from zeroone_ops.services.workflows.operational_summary import (
    format_operational_summary_publication,
)
from zeroone_ops.services.workflows.workflow_run_context import WorkflowRunContext


class WorkflowRunContextBuilder(Protocol):
    """Build repository-local state without selecting a provider."""

    def __call__(self, *, config: AppConfig, run_id: str, dry_run: bool) -> WorkflowRunContext:
        """Build the context for one workflow invocation."""


class DashboardPolicyViewBuilderFactory(Protocol):
    """Build legacy GitLab dashboard policy views on demand."""

    def __call__(
        self, *, repo_root: Path, config: AppConfig, state: AppState
    ) -> DashboardPolicyViewBuilder:
        """Build the dashboard policy view."""


class GitHubPolicyIssueServiceBuilder(Protocol):
    """Build GitHub policy access only after GitHub recovery is selected."""

    def __call__(
        self, *, repo_root: Path, config: AppConfig, state: AppState
    ) -> GitHubPolicyIssueService:
        """Build GitHub policy issue access."""


class GitLabPolicyIssueServiceBuilder(Protocol):
    """Build GitLab policy access only after issue-mode recovery is selected."""

    def __call__(
        self, *, repo_root: Path, config: AppConfig, state: AppState
    ) -> GitLabPolicyIssueService:
        """Build GitLab policy issue access."""


class GitHubRecoveryRunnerBuilder(Protocol):
    """Build GitHub recovery services after GitHub routing is selected."""

    def __call__(
        self, *, run_state_service: RunStateService
    ) -> tuple[GitHubWorkItemRecoveryRunner, GitHubWorkItemService]:
        """Build GitHub recovery processing and work-item lookup."""


class GitHubSummaryPublisher(Protocol):
    """Publish the optional GitHub operational summary."""

    def __call__(
        self,
        *,
        github_config: GitHubConnectionConfig,
        work_item_service: GitHubWorkItemService,
        latest_finding_sync: FindingSyncObservation | None,
    ) -> GitHubOperationalSummaryPublishResult | None:
        """Publish a derived GitHub summary."""


class GitLabSummaryPublisher(Protocol):
    """Publish the optional GitLab operational summary."""

    def __call__(
        self,
        *,
        gitlab_config: GitLabConnectionConfig,
        work_item_service: GitLabWorkItemService,
        latest_finding_sync: FindingSyncObservation | None,
    ) -> GitLabOperationalSummaryPublishResult | None:
        """Publish a derived GitLab summary."""


class RecoveryWorkflow:
    """Route provider-native recovery commands through the active control plane."""

    def __init__(
        self,
        *,
        config: AppConfig,
        dry_run: bool,
        publish_operational_summary: bool,
        build_run_id: Callable[[], str],
        build_context: WorkflowRunContextBuilder,
        is_gitlab_issue_mode: Callable[[AppConfig], bool],
        load_github_config: Callable[[], GitHubConnectionConfig],
        load_gitlab_config: Callable[[], GitLabConnectionConfig],
        load_github_issue_number: Callable[[], int | None],
        load_github_comment_id: Callable[[], int | None],
        build_dashboard_policy_view: DashboardPolicyViewBuilderFactory,
        build_github_policy_issue_service: GitHubPolicyIssueServiceBuilder,
        build_gitlab_policy_issue_service: GitLabPolicyIssueServiceBuilder,
        build_github_recovery_runner: GitHubRecoveryRunnerBuilder,
        publish_github_summary: GitHubSummaryPublisher,
        publish_gitlab_summary: GitLabSummaryPublisher,
    ) -> None:
        """Initialize recovery composition without loading provider settings."""
        self.config = config
        self.dry_run = dry_run
        self.publish_operational_summary = publish_operational_summary
        self.build_run_id = build_run_id
        self.build_context = build_context
        self.is_gitlab_issue_mode = is_gitlab_issue_mode
        self.load_github_config = load_github_config
        self.load_gitlab_config = load_gitlab_config
        self.load_github_issue_number = load_github_issue_number
        self.load_github_comment_id = load_github_comment_id
        self.build_dashboard_policy_view = build_dashboard_policy_view
        self.build_github_policy_issue_service = build_github_policy_issue_service
        self.build_gitlab_policy_issue_service = build_gitlab_policy_issue_service
        self.build_github_recovery_runner = build_github_recovery_runner
        self.publish_github_summary = publish_github_summary
        self.publish_gitlab_summary = publish_gitlab_summary

    def run(self) -> RunSummary:
        """Run recovery through the selected provider and control-plane route."""
        if self.config.platform == "github":
            return self._run_github_recovery()
        if self.is_gitlab_issue_mode(self.config):
            return self._run_gitlab_issue_recovery()
        return self._run_legacy_gitlab_dashboard_recovery()

    def _run_github_recovery(self) -> RunSummary:
        """Process the current GitHub issue-comment recovery command."""
        context = self._build_context()
        record = context.run_state_service.start_run(context.run_id)
        issue_number = self.load_github_issue_number()
        comment_id = self.load_github_comment_id()
        if issue_number is None or comment_id is None:
            message = "GitHub recovery requires an issue_comment workflow event."
            return context.run_state_service.fail_run(
                record=record,
                error_message=message,
                failure=FailureDetails(stage=FailureStage.DASHBOARD_UPDATE, message=message),
            )

        github_config = self.load_github_config()
        recovery_runner, work_item_service = self.build_github_recovery_runner(
            run_state_service=context.run_state_service
        )
        existing = next(
            (
                item
                for item in work_item_service.list_open_work_items(
                    repository_id=github_config.repository
                )
                if item.issue.number == issue_number
            ),
            None,
        )
        policy_eligible = False
        if existing is not None:
            policy_state = self.build_github_policy_issue_service(
                repo_root=context.repo_root,
                config=self.config,
                state=context.state,
            ).load_policy_state(
                repository_id=github_config.repository,
                persist=not context.active_dry_run,
            )
            policy_eligible = FindingWorkflowPolicyService().is_work_item_eligible(
                work_item=existing.work_item,
                policy_state=policy_state,
            )
        summary = recovery_runner.run(
            repository_id=github_config.repository,
            issue_number=issue_number,
            comment_id=comment_id,
            policy_eligible=policy_eligible,
            record=record,
            active_dry_run=context.active_dry_run,
            execution_mode=self.config.execution_mode,
        )
        if context.active_dry_run or summary.status != RunStatus.SYNCED:
            return summary
        publication = self.publish_github_summary(
            github_config=github_config,
            work_item_service=work_item_service,
            latest_finding_sync=None,
        )
        return replace(
            summary,
            message=summary.message + format_operational_summary_publication(publication),
        )

    def _run_gitlab_issue_recovery(self) -> RunSummary:
        """Poll authorized GitLab issue-mode recovery notes."""
        context = self._build_context()
        record = context.run_state_service.start_run(context.run_id)
        gitlab_config = self.load_gitlab_config()
        work_item_client = GitLabWorkItemClient(gitlab_config)
        work_item_service = GitLabWorkItemService(work_item_client)
        policy_state = self.build_gitlab_policy_issue_service(
            repo_root=context.repo_root,
            config=self.config,
            state=context.state,
        ).load_policy_state(
            project_id=gitlab_config.project_id,
            persist=not context.active_dry_run,
        )
        summary = GitLabWorkItemRecoveryRunner(
            recovery_service=GitLabWorkItemRecoveryService(
                note_client=work_item_client,
                note_authorization_service=GitLabPolicyNoteAuthorizationService(work_item_client),
                work_item_service=work_item_service,
            ),
            work_item_service=work_item_service,
            policy_service=FindingWorkflowPolicyService(),
            run_state_service=context.run_state_service,
        ).run(
            project_id=gitlab_config.project_id,
            policy_state=policy_state,
            record=record,
            active_dry_run=context.active_dry_run,
            execution_mode=self.config.execution_mode,
        )
        if (
            context.active_dry_run
            or summary.status != RunStatus.SYNCED
            or not self.publish_operational_summary
        ):
            return summary
        publication = self.publish_gitlab_summary(
            gitlab_config=gitlab_config,
            work_item_service=work_item_service,
            latest_finding_sync=None,
        )
        return replace(
            summary,
            message=summary.message + format_operational_summary_publication(publication),
        )

    def _run_legacy_gitlab_dashboard_recovery(self) -> RunSummary:
        """Run the explicit legacy GitLab dashboard recovery path."""
        context = self._build_context()
        record = context.run_state_service.start_run(context.run_id)
        gitlab_config = self.load_gitlab_config()
        return DashboardRecoveryRunner(
            recovery_service=DashboardRecoveryService(
                dashboard_service=DashboardService(
                    GitLabDashboardClient(gitlab_config),
                    policy_view_builder=self.build_dashboard_policy_view(
                        repo_root=context.repo_root,
                        config=self.config,
                        state=context.state,
                    ),
                )
            ),
            run_state_service=context.run_state_service,
        ).run(
            project_id=gitlab_config.project_id,
            record=record,
            active_dry_run=context.active_dry_run,
            execution_mode=self.config.execution_mode,
        )

    def _build_context(self) -> WorkflowRunContext:
        """Build shared repository-local state before provider configuration."""
        return self.build_context(
            config=self.config,
            run_id=self.build_run_id(),
            dry_run=self.dry_run,
        )
