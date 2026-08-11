"""Work-item lifecycle and legacy dashboard reconciliation composition."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from zeroone_ops.models.config import AppConfig, GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.state import (
    AppState,
    FailureDetails,
    FailureStage,
    RunRecord,
    RunStatus,
    utc_now,
)
from zeroone_ops.providers.github_client import GitHubClient
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.providers.review.gitlab import GitLabReviewClient
from zeroone_ops.services.control_plane.overview.github_operational_summary_service import (
    GitHubOperationalSummaryPublishResult,
)
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_service import (
    GitLabOperationalSummaryPublishResult,
)
from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    FindingSyncObservation,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lifecycle_service import (
    GitHubWorkItemLifecycleResult,
    GitHubWorkItemLifecycleService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lifecycle_service import (
    GitLabWorkItemLifecycleResult,
    GitLabWorkItemLifecycleService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.dashboard.dashboard_policy_view_builder import (
    DashboardPolicyViewBuilder,
)
from zeroone_ops.services.dashboard.dashboard_reconciliation_runner import (
    DashboardReconciliationRunner,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.shared.run_state_service import RunSummary
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


class WorkItemLifecycleWorkflow:
    """Route lifecycle synchronization through the configured control plane."""

    def __init__(
        self,
        *,
        config: AppConfig,
        dry_run: bool,
        build_run_id: Callable[[], str],
        build_context: WorkflowRunContextBuilder,
        is_gitlab_issue_mode: Callable[[AppConfig], bool],
        load_github_config: Callable[[], GitHubConnectionConfig],
        load_gitlab_config: Callable[[], GitLabConnectionConfig],
        build_dashboard_policy_view: DashboardPolicyViewBuilderFactory,
        publish_github_summary: GitHubSummaryPublisher,
        publish_gitlab_summary: GitLabSummaryPublisher,
    ) -> None:
        """Initialize lifecycle composition without loading provider settings."""
        self.config = config
        self.dry_run = dry_run
        self.build_run_id = build_run_id
        self.build_context = build_context
        self.is_gitlab_issue_mode = is_gitlab_issue_mode
        self.load_github_config = load_github_config
        self.load_gitlab_config = load_gitlab_config
        self.build_dashboard_policy_view = build_dashboard_policy_view
        self.publish_github_summary = publish_github_summary
        self.publish_gitlab_summary = publish_gitlab_summary

    def run_status_sync(self) -> RunSummary:
        """Reconcile lifecycle state for the active platform."""
        if self.config.platform == "github":
            return self._run_github_lifecycle()
        if self.is_gitlab_issue_mode(self.config):
            return self._run_gitlab_issue_lifecycle()
        return self.run_legacy_dashboard_reconciliation()

    def run_legacy_dashboard_reconciliation(self) -> RunSummary:
        """Run the explicit legacy GitLab dashboard reconciliation path."""
        context = self._build_context()
        record = context.run_state_service.start_run(context.run_id)
        gitlab_config = self.load_gitlab_config()
        return DashboardReconciliationRunner(
            config=self.config,
            dashboard_service=DashboardService(
                GitLabDashboardClient(gitlab_config),
                policy_view_builder=self.build_dashboard_policy_view(
                    repo_root=context.repo_root,
                    config=self.config,
                    state=context.state,
                ),
            ),
            review_client=GitLabReviewClient(gitlab_config),
            run_state_service=context.run_state_service,
        ).run(
            project_id=gitlab_config.project_id,
            record=record,
            run_id=context.run_id,
            active_dry_run=context.active_dry_run,
            execution_mode=self.config.execution_mode,
        )

    def _run_github_lifecycle(self) -> RunSummary:
        """Converge GitHub work-item state from pull-request state."""
        context = self._build_context()
        record = context.run_state_service.start_run(context.run_id)
        if not context.active_dry_run and self.config.execution_mode != "ci":
            return self._local_lifecycle_failure(
                context=context,
                record=record,
                provider="GitHub",
            )

        github_config = self.load_github_config()
        work_item_service = GitHubWorkItemService(GitHubWorkItemClient(github_config))
        result = GitHubWorkItemLifecycleService(
            work_item_service=work_item_service,
            change_request_client=GitHubClient(github_config),
        ).reconcile(
            repository_id=github_config.repository,
            now=utc_now(),
            persist=not context.active_dry_run,
        )
        publication = (
            self.publish_github_summary(
                github_config=github_config,
                work_item_service=work_item_service,
                latest_finding_sync=None,
            )
            if not context.active_dry_run
            else None
        )
        return self._build_lifecycle_summary(
            context=context,
            record=record,
            result=result,
            provider="GitHub",
            publication=publication,
        )

    def _run_gitlab_issue_lifecycle(self) -> RunSummary:
        """Converge GitLab issue-mode work-item state from merge-request state."""
        context = self._build_context()
        record = context.run_state_service.start_run(context.run_id)
        if not context.active_dry_run and self.config.execution_mode != "ci":
            return self._local_lifecycle_failure(
                context=context,
                record=record,
                provider="GitLab",
            )

        gitlab_config = self.load_gitlab_config()
        work_item_service = GitLabWorkItemService(GitLabWorkItemClient(gitlab_config))
        result = GitLabWorkItemLifecycleService(
            work_item_service=work_item_service,
            change_request_client=GitLabReviewClient(gitlab_config),
        ).reconcile(
            project_id=gitlab_config.project_id,
            now=utc_now(),
            persist=not context.active_dry_run,
        )
        publication = (
            self.publish_gitlab_summary(
                gitlab_config=gitlab_config,
                work_item_service=work_item_service,
                latest_finding_sync=None,
            )
            if not context.active_dry_run
            else None
        )
        return self._build_lifecycle_summary(
            context=context,
            record=record,
            result=result,
            provider="GitLab",
            publication=publication,
        )

    def _local_lifecycle_failure(
        self,
        *,
        context: WorkflowRunContext,
        record: RunRecord,
        provider: str,
    ) -> RunSummary:
        """Fail live local lifecycle execution with the existing provider wording."""
        message = (
            f"{provider} work-item lifecycle execution is only supported in CI mode. "
            "Use --dry-run locally."
        )
        return context.run_state_service.fail_run(
            record=record,
            error_message=message,
            failure=FailureDetails(stage=FailureStage.RECONCILIATION, message=message),
        )

    def _build_lifecycle_summary(
        self,
        *,
        context: WorkflowRunContext,
        record: RunRecord,
        result: GitHubWorkItemLifecycleResult | GitLabWorkItemLifecycleResult,
        provider: str,
        publication: (
            GitHubOperationalSummaryPublishResult | GitLabOperationalSummaryPublishResult | None
        ),
    ) -> RunSummary:
        """Persist and render the unchanged lifecycle reconciliation result."""
        record.status = RunStatus.RECONCILED
        record.updated_at = utc_now()
        context.state_store.save(context.state)
        prefix = "Dry-run would reconcile" if context.active_dry_run else "Reconciled"
        return context.run_state_service.build_summary(
            run_id=context.run_id,
            status=record.status,
            message=(
                f"{prefix} {provider} remediation work items: "
                f"stale claims recovered={result.recovered_stale_claim_count}; "
                f"completed={result.completed_count}; "
                f"closed native issues={result.closed_issue_count}; "
                f"blocked={result.blocked_count}; "
                f"in progress={result.in_progress_count}."
                + format_operational_summary_publication(publication)
            ),
        )

    def _build_context(self) -> WorkflowRunContext:
        """Build shared repository-local state before provider configuration."""
        return self.build_context(
            config=self.config,
            run_id=self.build_run_id(),
            dry_run=self.dry_run,
        )
