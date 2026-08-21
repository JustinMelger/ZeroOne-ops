"""Review workflow composition for GitHub and GitLab."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from zeroone_ops.models.config import AppConfig
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.providers.review.platform import ChangeRequestReviewPlatformProtocol
from zeroone_ops.services.observability.workflow_trace_service import (
    WorkflowTraceContext,
    WorkflowTraceService,
    workflow_execution_url,
    workflow_model,
)
from zeroone_ops.services.review.pipeline.review_runner import ReviewRunner
from zeroone_ops.services.review.state.review_state_service import ReviewStateService
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.workflows.workflow_run_context import WorkflowRunContext
from zeroone_ops.settings import load_mlflow_tracing_config


class WorkflowRunContextBuilder(Protocol):
    """Build repository-local state without selecting a provider."""

    def __call__(self, *, config: AppConfig, run_id: str, dry_run: bool) -> WorkflowRunContext:
        """Build the context for one workflow invocation."""


class ReviewPlatformRuntimeBuilder(Protocol):
    """Build review transport and event inputs for the active provider."""

    def __call__(
        self,
        config: AppConfig,
    ) -> tuple[
        ChangeRequestReviewPlatformProtocol,
        str,
        int | None,
        str | None,
        GitLabDashboardClient | None,
    ]:
        """Build the provider-local review runtime."""


class ReviewWorkflow:
    """Compose one staged change-request review without owning review decisions."""

    def __init__(
        self,
        *,
        config: AppConfig,
        dry_run: bool,
        build_run_id: Callable[[], str],
        build_context: WorkflowRunContextBuilder,
        build_platform_runtime: ReviewPlatformRuntimeBuilder,
    ) -> None:
        """Initialize review composition without loading provider settings."""
        self.config = config
        self.dry_run = dry_run
        self.build_run_id = build_run_id
        self.build_context = build_context
        self.build_platform_runtime = build_platform_runtime

    def run(self) -> RunSummary:
        """Run the staged review pipeline with provider-local event context."""
        context = self.build_context(
            config=self.config,
            run_id=self.build_run_id(),
            dry_run=self.dry_run,
        )
        review_state_service = ReviewStateService(
            state_store=context.state_store,
            state=context.state,
            max_prior_review_passes=self.config.review.max_prior_review_passes,
        )
        record = review_state_service.start_run(context.run_id)
        (
            review_client,
            repository_id,
            current_change_request_number,
            triggered_head_sha,
            dashboard_client,
        ) = self.build_platform_runtime(self.config)
        runner = ReviewRunner(
            repo_root=context.repo_root,
            config=self.config,
            review_client=review_client,
            dashboard_client=dashboard_client,
            review_state_service=review_state_service,
        )
        if context.active_dry_run:
            return runner.run(
                repository_id=repository_id,
                current_change_request_number=current_change_request_number,
                triggered_head_sha=triggered_head_sha,
                record=record,
                run_id=context.run_id,
                active_dry_run=True,
            )
        with WorkflowTraceService(load_mlflow_tracing_config()).trace(
            WorkflowTraceContext(
                workflow="review",
                run_id=context.run_id,
                platform=self.config.platform,
                repository=repository_id,
                execution_mode=self.config.execution_mode,
                model=workflow_model(),
                workflow_url=workflow_execution_url(),
                change_request_number=current_change_request_number,
            )
        ) as trace:
            summary = runner.run(
                repository_id=repository_id,
                current_change_request_number=current_change_request_number,
                triggered_head_sha=triggered_head_sha,
                record=record,
                run_id=context.run_id,
                active_dry_run=False,
            )
            trace.complete(summary=summary, failure=record.failure)
            return summary
