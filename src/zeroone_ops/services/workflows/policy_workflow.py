"""Policy workflow composition for GitHub and GitLab."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from zeroone_ops.models.config import AppConfig, GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.state import AppState, RunRecord, RunStatus
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_service import (
    GitLabOperationalSummaryPublishResult,
)
from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    FindingSyncObservation,
)
from zeroone_ops.services.control_plane.policy.github_policy_processing_runner import (
    GitHubPolicyProcessingRunner,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_processing_runner import (
    GitLabPolicyProcessingRunner,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.dashboard.dashboard_policy_processing_runner import (
    DashboardPolicyProcessingRunner,
)
from zeroone_ops.services.dashboard.dashboard_policy_view_builder import (
    DashboardPolicyViewBuilder,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
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
    """Build a legacy GitLab dashboard policy view on demand."""

    def __call__(
        self, *, repo_root: Path, config: AppConfig, state: AppState
    ) -> DashboardPolicyViewBuilder:
        """Build the dashboard policy view."""


class GitHubPolicyProcessingRunnerBuilder(Protocol):
    """Build GitHub policy processing after GitHub routing is selected."""

    def __call__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        state: AppState,
        run_state_service: RunStateService,
    ) -> GitHubPolicyProcessingRunner:
        """Build GitHub policy processing."""


class GitLabPolicyProcessingRunnerBuilder(Protocol):
    """Build GitLab policy processing after issue-mode routing is selected."""

    def __call__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        state: AppState,
        run_state_service: RunStateService,
    ) -> GitLabPolicyProcessingRunner:
        """Build GitLab policy processing."""


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


class PolicyWorkflow:
    """Route policy processing through the configured provider control plane."""

    def __init__(
        self,
        *,
        config: AppConfig,
        dry_run: bool,
        publish_operational_summary: bool,
        build_run_id: Callable[[], str],
        build_context: WorkflowRunContextBuilder,
        load_github_config: Callable[[], GitHubConnectionConfig],
        load_gitlab_config: Callable[[], GitLabConnectionConfig],
        build_dashboard_policy_view: DashboardPolicyViewBuilderFactory,
        build_github_policy_runner: GitHubPolicyProcessingRunnerBuilder,
        build_gitlab_policy_runner: GitLabPolicyProcessingRunnerBuilder,
        publish_gitlab_summary: GitLabSummaryPublisher,
    ) -> None:
        """Initialize policy composition without loading provider settings."""
        self.config = config
        self.dry_run = dry_run
        self.publish_operational_summary = publish_operational_summary
        self.build_run_id = build_run_id
        self.build_context = build_context
        self.load_github_config = load_github_config
        self.load_gitlab_config = load_gitlab_config
        self.build_dashboard_policy_view = build_dashboard_policy_view
        self.build_github_policy_runner = build_github_policy_runner
        self.build_gitlab_policy_runner = build_gitlab_policy_runner
        self.publish_gitlab_summary = publish_gitlab_summary

    def run(self) -> RunSummary:
        """Run policy processing through the selected provider route."""
        context = self._build_context()
        record = context.run_state_service.start_run(context.run_id)
        if self.config.platform == "github":
            return self._run_github(context=context, record=record)

        gitlab_config = self.load_gitlab_config()
        gitlab_settings = self.config.require_gitlab_config(reason="GitLab policy processing")
        if gitlab_settings.control_plane_mode == "issues":
            return self._run_gitlab_issue_mode(
                context=context,
                record=record,
                gitlab_config=gitlab_config,
            )
        return self._run_legacy_gitlab_dashboard(
            context=context,
            record=record,
            gitlab_config=gitlab_config,
        )

    def _run_github(self, *, context: WorkflowRunContext, record: RunRecord) -> RunSummary:
        """Process the dedicated GitHub policy issue."""
        github_config = self.load_github_config()
        return self.build_github_policy_runner(
            repo_root=context.repo_root,
            config=self.config,
            state=context.state,
            run_state_service=context.run_state_service,
        ).run(
            repository_id=github_config.repository,
            record=record,
            active_dry_run=context.active_dry_run,
            execution_mode=self.config.execution_mode,
        )

    def _run_gitlab_issue_mode(
        self,
        *,
        context: WorkflowRunContext,
        record: RunRecord,
        gitlab_config: GitLabConnectionConfig,
    ) -> RunSummary:
        """Process GitLab issue-mode policy and refresh its derived summary."""
        summary = self.build_gitlab_policy_runner(
            repo_root=context.repo_root,
            config=self.config,
            state=context.state,
            run_state_service=context.run_state_service,
        ).run(
            project_id=gitlab_config.project_id,
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
            work_item_service=GitLabWorkItemService(GitLabWorkItemClient(gitlab_config)),
            latest_finding_sync=None,
        )
        return replace(
            summary,
            message=summary.message + format_operational_summary_publication(publication),
        )

    def _run_legacy_gitlab_dashboard(
        self,
        *,
        context: WorkflowRunContext,
        record: RunRecord,
        gitlab_config: GitLabConnectionConfig,
    ) -> RunSummary:
        """Run the explicit legacy GitLab dashboard policy route."""
        return DashboardPolicyProcessingRunner(
            dashboard_service=DashboardService(
                GitLabDashboardClient(gitlab_config),
                policy_view_builder=self.build_dashboard_policy_view(
                    repo_root=context.repo_root,
                    config=self.config,
                    state=context.state,
                ),
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
