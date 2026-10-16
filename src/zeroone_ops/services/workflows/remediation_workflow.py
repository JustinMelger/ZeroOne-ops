"""Remediation workflow composition for GitHub and GitLab."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from typing import Protocol

from zeroone_ops.models.config import AppConfig, GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.state import RunStatus
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
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
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.observability.workflow_trace_service import (
    WorkflowTraceContext,
    WorkflowTraceScope,
    WorkflowTraceService,
    workflow_execution_url,
    workflow_model,
)
from zeroone_ops.services.remediation.github_remediation_runner import (
    GitHubRemediationRunner,
)
from zeroone_ops.services.remediation.gitlab_remediation_runner import (
    GitLabRemediationRunner,
)
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.workflows.operational_summary import (
    format_operational_summary_publication,
)
from zeroone_ops.services.workflows.workflow_run_context import WorkflowRunContext
from zeroone_ops.settings import load_mlflow_tracing_config


class WorkflowRunContextBuilder(Protocol):
    """Build repository-local state without selecting a provider."""

    def __call__(
        self,
        *,
        config: AppConfig,
        run_id: str,
        dry_run: bool,
    ) -> WorkflowRunContext:
        """Build the context for one workflow invocation."""


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


class RemediationWorkflow:
    """Route remediation through the configured provider control plane."""

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
        publish_github_summary: GitHubSummaryPublisher,
        publish_gitlab_summary: GitLabSummaryPublisher,
    ) -> None:
        """Initialize workflow composition without loading provider settings."""
        self.config = config
        self.dry_run = dry_run
        self.publish_operational_summary = publish_operational_summary
        self.build_run_id = build_run_id
        self.build_context = build_context
        self.load_github_config = load_github_config
        self.load_gitlab_config = load_gitlab_config
        self.publish_github_summary = publish_github_summary
        self.publish_gitlab_summary = publish_gitlab_summary

    def run(self) -> RunSummary:
        """Run the explicit provider and control-plane remediation route."""
        if self.config.platform == "github":
            return self._run_github_work_item_remediation()
        return self._run_gitlab_issue_remediation()

    def _run_github_work_item_remediation(self) -> RunSummary:
        """Run one GitHub work-item remediation and refresh its derived summary."""
        context = self._build_context()
        record = context.run_state_service.start_run(context.run_id)
        github_config = self.load_github_config()
        work_item_service = GitHubWorkItemService(GitHubWorkItemClient(github_config))
        runner = GitHubRemediationRunner(
            repo_root=context.repo_root,
            config=self.config,
            repository_id=github_config.repository,
            work_item_service=work_item_service,
            run_state_service=context.run_state_service,
        )
        if context.active_dry_run:
            return runner.run(record=record, active_dry_run=True)
        with self._remediation_trace(context=context, repository=github_config.repository) as trace:
            summary = runner.run(record=record, active_dry_run=False)
            if summary.status != RunStatus.NO_ISSUE:
                publication = self.publish_github_summary(
                    github_config=github_config,
                    work_item_service=work_item_service,
                    latest_finding_sync=None,
                )
                summary = replace(
                    summary,
                    message=summary.message + format_operational_summary_publication(publication),
                )
            trace.complete(summary=summary, failure=record.failure)
            return summary

    def _run_gitlab_issue_remediation(self) -> RunSummary:
        """Run one GitLab issue-mode remediation and optionally refresh its summary."""
        context = self._build_context()
        record = context.run_state_service.start_run(context.run_id)
        gitlab_config = self.load_gitlab_config()
        work_item_service = GitLabWorkItemService(GitLabWorkItemClient(gitlab_config))
        runner = GitLabRemediationRunner(
            repo_root=context.repo_root,
            config=self.config,
            project_id=gitlab_config.project_id,
            work_item_service=work_item_service,
            run_state_service=context.run_state_service,
        )
        if context.active_dry_run:
            return runner.run(record=record, active_dry_run=True)
        with self._remediation_trace(context=context, repository=gitlab_config.project_id) as trace:
            summary = runner.run(record=record, active_dry_run=False)
            if summary.status != RunStatus.NO_ISSUE and self.publish_operational_summary:
                publication = self.publish_gitlab_summary(
                    gitlab_config=gitlab_config,
                    work_item_service=work_item_service,
                    latest_finding_sync=None,
                )
                summary = replace(
                    summary,
                    message=summary.message + format_operational_summary_publication(publication),
                )
            trace.complete(summary=summary, failure=record.failure)
            return summary

    def _remediation_trace(
        self,
        *,
        context: WorkflowRunContext,
        repository: str,
    ) -> AbstractContextManager[WorkflowTraceScope]:
        """Build the optional root trace for one live remediation execution."""
        return WorkflowTraceService(load_mlflow_tracing_config()).trace(
            WorkflowTraceContext(
                workflow="remediation",
                run_id=context.run_id,
                platform=self.config.platform,
                repository=repository,
                execution_mode=self.config.execution_mode,
                model=workflow_model(),
                workflow_url=workflow_execution_url(),
            )
        )

    def _build_context(self) -> WorkflowRunContext:
        """Build shared repository-local state before provider configuration."""
        return self.build_context(
            config=self.config,
            run_id=self.build_run_id(),
            dry_run=self.dry_run,
        )
