"""Application runner.

This module acts as the composition root for the bot workflow.
"""

from __future__ import annotations

import secrets
from dataclasses import replace
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.state import RunStatus, utc_now
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.dashboard.dashboard_policy_processing_runner import (
    DashboardPolicyProcessingRunner,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.review.pipeline.review_runner import ReviewRunner
from zeroone_ops.services.review.state.review_state_service import ReviewStateService
from zeroone_ops.services.shared.run_state_service import (
    RunStateService,
    RunSummary,
)
from zeroone_ops.services.shared.state_store import StateStore
from zeroone_ops.services.workflows.finding_sync_workflow import FindingSyncWorkflow
from zeroone_ops.services.workflows.gitlab_issue_control_plane_workflow import (
    GitLabIssueControlPlaneWorkflow,
)
from zeroone_ops.services.workflows.operational_summary import (
    format_operational_summary_publication as _format_operational_summary_publication,
)
from zeroone_ops.services.workflows.operational_summary import (
    publish_github_operational_summary as _publish_github_operational_summary,
)
from zeroone_ops.services.workflows.operational_summary import (
    publish_gitlab_operational_summary as _publish_gitlab_operational_summary,
)
from zeroone_ops.services.workflows.provider_workflow_builders import (
    build_dashboard_policy_view_builder,
    build_github_policy_issue_service,
    build_github_policy_processing_runner,
    build_github_work_item_recovery_runner,
    build_gitlab_policy_issue_service,
    build_gitlab_policy_processing_runner,
    build_review_platform_runtime,
)
from zeroone_ops.services.workflows.recovery_workflow import RecoveryWorkflow
from zeroone_ops.services.workflows.remediation_workflow import RemediationWorkflow
from zeroone_ops.services.workflows.work_item_lifecycle_workflow import (
    WorkItemLifecycleWorkflow,
)
from zeroone_ops.services.workflows.workflow_run_context import build_workflow_run_context
from zeroone_ops.settings import (
    load_config,
    load_current_github_issue_comment_id,
    load_current_github_issue_number,
    load_github_connection_config,
    load_gitlab_connection_config,
    load_gitlab_project_id_override,
    load_sonarqube_project_key_override,
)


def _build_run_id() -> str:
    """Build a unique run identifier."""
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def review(*, dry_run: bool = False) -> RunSummary:
    """Run the merge-request review workflow."""
    config = load_config()
    context = build_workflow_run_context(
        config=config,
        run_id=_build_run_id(),
        dry_run=dry_run,
    )
    review_state_service = ReviewStateService(
        state_store=context.state_store,
        state=context.state,
        max_prior_review_passes=config.review.max_prior_review_passes,
    )

    record = review_state_service.start_run(context.run_id)
    (
        review_client,
        repository_id,
        current_change_request_number,
        triggered_head_sha,
        dashboard_client,
    ) = build_review_platform_runtime(config)
    return ReviewRunner(
        repo_root=context.repo_root,
        config=config,
        review_client=review_client,
        dashboard_client=dashboard_client,
        review_state_service=review_state_service,
    ).run(
        repository_id=repository_id,
        current_change_request_number=current_change_request_number,
        triggered_head_sha=triggered_head_sha,
        record=record,
        run_id=context.run_id,
        active_dry_run=context.active_dry_run,
    )


def dashboard_remediate(*, dry_run: bool = False) -> RunSummary:
    """Run the legacy GitLab dashboard remediation command."""
    return run_remediation(dry_run=dry_run)


def run_remediation(
    *,
    dry_run: bool = False,
    publish_operational_summary: bool = True,
) -> RunSummary:
    """Run remediation for the active platform."""
    config = load_config()
    return RemediationWorkflow(
        config=config,
        dry_run=dry_run,
        publish_operational_summary=publish_operational_summary,
        build_run_id=_build_run_id,
        build_context=build_workflow_run_context,
        is_gitlab_issue_mode=_gitlab_issue_mode_is_active,
        load_github_config=load_github_connection_config,
        load_gitlab_config=load_gitlab_connection_config,
        build_dashboard_policy_view=build_dashboard_policy_view_builder,
        publish_github_summary=_publish_github_operational_summary,
        publish_gitlab_summary=_publish_gitlab_operational_summary,
    ).run()


def sync_dashboard_sonar(*, dry_run: bool = False) -> RunSummary:
    """Run the legacy GitLab findings-sync command."""
    return sync_findings(dry_run=dry_run)


def sync_findings(*, dry_run: bool = False) -> RunSummary:
    """Collect normalized findings and project them for the active platform."""
    config = load_config()
    return FindingSyncWorkflow(
        config=config,
        dry_run=dry_run,
        build_run_id=_build_run_id,
        build_context=build_workflow_run_context,
        is_gitlab_issue_mode=_gitlab_issue_mode_is_active,
        load_github_config=load_github_connection_config,
        load_gitlab_config=load_gitlab_connection_config,
        build_dashboard_policy_view=build_dashboard_policy_view_builder,
        build_github_policy_issue_service=build_github_policy_issue_service,
        build_gitlab_policy_issue_service=build_gitlab_policy_issue_service,
        publish_github_summary=_publish_github_operational_summary,
        publish_gitlab_summary=_publish_gitlab_operational_summary,
    ).run()


def dashboard_reconcile(*, dry_run: bool = False) -> RunSummary:
    """Run the legacy GitLab dashboard reconciliation command."""
    config = load_config()
    if _gitlab_issue_mode_is_active(config):
        return _issue_mode_workflow_unavailable_summary(
            config=config,
            workflow="dashboard reconciliation",
        )
    return _build_work_item_lifecycle_workflow(
        config=config,
        dry_run=dry_run,
    ).run_legacy_dashboard_reconciliation()


def sync_work_item_status(*, dry_run: bool = False) -> RunSummary:
    """Reconcile remediation work-item lifecycle state for the active platform."""
    config = load_config()
    return _build_work_item_lifecycle_workflow(config=config, dry_run=dry_run).run_status_sync()


def _build_work_item_lifecycle_workflow(
    *,
    config: AppConfig,
    dry_run: bool,
) -> WorkItemLifecycleWorkflow:
    """Compose lifecycle routes while keeping provider configuration lazy."""
    return WorkItemLifecycleWorkflow(
        config=config,
        dry_run=dry_run,
        build_run_id=_build_run_id,
        build_context=build_workflow_run_context,
        is_gitlab_issue_mode=_gitlab_issue_mode_is_active,
        load_github_config=load_github_connection_config,
        load_gitlab_config=load_gitlab_connection_config,
        build_dashboard_policy_view=build_dashboard_policy_view_builder,
        publish_github_summary=_publish_github_operational_summary,
        publish_gitlab_summary=_publish_gitlab_operational_summary,
    )


def recover_work_item(
    *,
    dry_run: bool = False,
    publish_operational_summary: bool = True,
) -> RunSummary:
    """Process provider-local remediation recovery commands."""
    config = load_config()
    return RecoveryWorkflow(
        config=config,
        dry_run=dry_run,
        publish_operational_summary=publish_operational_summary,
        build_run_id=_build_run_id,
        build_context=build_workflow_run_context,
        is_gitlab_issue_mode=_gitlab_issue_mode_is_active,
        load_github_config=load_github_connection_config,
        load_gitlab_config=load_gitlab_connection_config,
        load_github_issue_number=load_current_github_issue_number,
        load_github_comment_id=load_current_github_issue_comment_id,
        build_dashboard_policy_view=build_dashboard_policy_view_builder,
        build_github_policy_issue_service=build_github_policy_issue_service,
        build_gitlab_policy_issue_service=build_gitlab_policy_issue_service,
        build_github_recovery_runner=build_github_work_item_recovery_runner,
        publish_github_summary=_publish_github_operational_summary,
        publish_gitlab_summary=_publish_gitlab_operational_summary,
    ).run()


def run_gitlab_issue_control_plane(*, dry_run: bool = False) -> RunSummary:
    """Run GitLab issue-mode policy, recovery, and remediation as one operation."""
    config = load_config()
    if not _gitlab_issue_mode_is_active(config):
        return _issue_mode_workflow_unavailable_summary(
            config=config,
            workflow="GitLab issue control plane",
        )

    def publish_overview() -> str:
        # A blocked remediation can still have changed authoritative work-item state.
        gitlab_config = load_gitlab_connection_config()
        publication = _publish_gitlab_operational_summary(
            gitlab_config=gitlab_config,
            work_item_service=GitLabWorkItemService(GitLabWorkItemClient(gitlab_config)),
            latest_finding_sync=None,
        )
        return _format_operational_summary_publication(publication)

    return GitLabIssueControlPlaneWorkflow(
        run_policy=dashboard_policy,
        run_recovery=recover_work_item,
        run_remediation=run_remediation,
        publish_overview=publish_overview,
    ).run(config=config, dry_run=dry_run)


def dashboard_policy(
    *,
    dry_run: bool = False,
    publish_operational_summary: bool = True,
) -> RunSummary:
    """Run dedicated policy processing on the active platform."""
    config = load_config()
    repo_root = Path.cwd()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=load_gitlab_project_id_override(),
        sonarqube_project_key=load_sonarqube_project_key_override(),
    )
    state = state_store.load()
    run_state_service = RunStateService(config=config, state_store=state_store, state=state)

    run_id = _build_run_id()
    record = run_state_service.start_run(run_id)
    active_dry_run = dry_run or config.dry_run

    if config.platform == "github":
        github_config = load_github_connection_config()
        return build_github_policy_processing_runner(
            repo_root=repo_root,
            config=config,
            state=state,
            run_state_service=run_state_service,
        ).run(
            repository_id=github_config.repository,
            record=record,
            active_dry_run=active_dry_run,
            execution_mode=config.execution_mode,
        )

    gitlab_config = load_gitlab_connection_config()
    gitlab_settings = config.require_gitlab_config(reason="GitLab policy processing")
    if gitlab_settings.control_plane_mode == "issues":
        summary = build_gitlab_policy_processing_runner(
            repo_root=repo_root,
            config=config,
            state=state,
            run_state_service=run_state_service,
        ).run(
            project_id=gitlab_config.project_id,
            record=record,
            active_dry_run=active_dry_run,
            execution_mode=config.execution_mode,
        )
        if active_dry_run or summary.status != RunStatus.SYNCED or not publish_operational_summary:
            return summary
        publication = _publish_gitlab_operational_summary(
            gitlab_config=gitlab_config,
            work_item_service=GitLabWorkItemService(GitLabWorkItemClient(gitlab_config)),
            latest_finding_sync=None,
        )
        return replace(
            summary,
            message=summary.message + _format_operational_summary_publication(publication),
        )
    return DashboardPolicyProcessingRunner(
        dashboard_service=DashboardService(
            GitLabDashboardClient(gitlab_config),
            policy_view_builder=build_dashboard_policy_view_builder(
                repo_root=repo_root,
                config=config,
                state=state,
            ),
        ),
        run_state_service=run_state_service,
    ).run(
        project_id=gitlab_config.project_id,
        record=record,
        active_dry_run=active_dry_run,
        execution_mode=config.execution_mode,
    )


def _gitlab_issue_mode_is_active(config: AppConfig) -> bool:
    """Return whether GitLab issue mode owns the configured control plane."""
    return (
        config.platform == "gitlab"
        and config.require_gitlab_config(reason="GitLab issue control plane").control_plane_mode
        == "issues"
    )


def _issue_mode_workflow_unavailable_summary(*, config: AppConfig, workflow: str) -> RunSummary:
    """Fail closed until the requested GitLab issue-mode workflow is implemented."""
    return RunSummary(
        run_id=_build_run_id(),
        status=RunStatus.FAILED,
        message=(
            f"GitLab issue control-plane {workflow} is not available yet. "
            "Policy processing is the only supported issue-mode workflow in Phase 8b; "
            "keep gitlab.control_plane_mode=dashboard for other workflows."
        ),
        state_path=config.state.path,
    )
