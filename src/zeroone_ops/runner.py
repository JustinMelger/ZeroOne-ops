"""Application runner.

This module acts as the composition root for the bot workflow.
"""

from __future__ import annotations

import secrets

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.state import RunStatus, utc_now
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.workflows.finding_sync_workflow import FindingSyncWorkflow
from zeroone_ops.services.workflows.gitlab_issue_control_plane_workflow import (
    GitLabIssueControlPlaneWorkflow,
)
from zeroone_ops.services.workflows.operational_summary import (
    publish_github_operational_summary as _publish_github_operational_summary,
)
from zeroone_ops.services.workflows.operational_summary import (
    publish_gitlab_operational_summary as _publish_gitlab_operational_summary,
)
from zeroone_ops.services.workflows.operational_summary import (
    refresh_gitlab_operational_summary as _refresh_gitlab_operational_summary,
)
from zeroone_ops.services.workflows.policy_workflow import PolicyWorkflow
from zeroone_ops.services.workflows.provider_workflow_builders import (
    build_github_policy_issue_service,
    build_github_policy_processing_runner,
    build_github_work_item_recovery_runner,
    build_gitlab_policy_issue_service,
    build_gitlab_policy_processing_runner,
    build_review_platform_runtime,
    build_review_projection_factory,
    build_review_remediation_context_resolver,
)
from zeroone_ops.services.workflows.recovery_workflow import RecoveryWorkflow
from zeroone_ops.services.workflows.remediation_workflow import RemediationWorkflow
from zeroone_ops.services.workflows.review_workflow import ReviewWorkflow
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
)


def _build_run_id() -> str:
    """Build a unique run identifier."""
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def review(*, dry_run: bool = False) -> RunSummary:
    """Run the merge-request review workflow."""
    config = load_config()
    return ReviewWorkflow(
        config=config,
        dry_run=dry_run,
        build_run_id=_build_run_id,
        build_context=build_workflow_run_context,
        build_platform_runtime=build_review_platform_runtime,
        build_remediation_context_resolver=build_review_remediation_context_resolver,
        build_projection_factory=build_review_projection_factory,
    ).run()


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
        load_github_config=load_github_connection_config,
        load_gitlab_config=load_gitlab_connection_config,
        publish_github_summary=_publish_github_operational_summary,
        publish_gitlab_summary=_publish_gitlab_operational_summary,
    ).run()


def sync_findings(*, dry_run: bool = False) -> RunSummary:
    """Collect normalized findings and project them for the active platform."""
    config = load_config()
    return FindingSyncWorkflow(
        config=config,
        dry_run=dry_run,
        build_run_id=_build_run_id,
        build_context=build_workflow_run_context,
        load_github_config=load_github_connection_config,
        load_gitlab_config=load_gitlab_connection_config,
        build_github_policy_issue_service=build_github_policy_issue_service,
        build_gitlab_policy_issue_service=build_gitlab_policy_issue_service,
        publish_github_summary=_publish_github_operational_summary,
        publish_gitlab_summary=_publish_gitlab_operational_summary,
    ).run()


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
        load_github_config=load_github_connection_config,
        load_gitlab_config=load_gitlab_connection_config,
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
        load_github_config=load_github_connection_config,
        load_gitlab_config=load_gitlab_connection_config,
        load_github_issue_number=load_current_github_issue_number,
        load_github_comment_id=load_current_github_issue_comment_id,
        build_github_policy_issue_service=build_github_policy_issue_service,
        build_gitlab_policy_issue_service=build_gitlab_policy_issue_service,
        build_github_recovery_runner=build_github_work_item_recovery_runner,
        publish_github_summary=_publish_github_operational_summary,
        publish_gitlab_summary=_publish_gitlab_operational_summary,
    ).run()


def run_gitlab_issue_control_plane(*, dry_run: bool = False) -> RunSummary:
    """Run GitLab issue-mode policy, recovery, and remediation as one operation."""
    config = load_config()
    if config.platform != "gitlab":
        return RunSummary(
            run_id=_build_run_id(),
            status=RunStatus.FAILED,
            message="The combined control plane is supported only for GitLab.",
            state_path=config.state.path,
        )

    return GitLabIssueControlPlaneWorkflow(
        run_policy=run_policy,
        run_recovery=recover_work_item,
        run_remediation=run_remediation,
        publish_overview=_refresh_gitlab_operational_summary,
    ).run(config=config, dry_run=dry_run)


def run_policy(
    *,
    dry_run: bool = False,
    publish_operational_summary: bool = True,
) -> RunSummary:
    """Run dedicated policy processing on the active platform."""
    config = load_config()
    return PolicyWorkflow(
        config=config,
        dry_run=dry_run,
        publish_operational_summary=publish_operational_summary,
        build_run_id=_build_run_id,
        build_context=build_workflow_run_context,
        load_github_config=load_github_connection_config,
        load_gitlab_config=load_gitlab_connection_config,
        build_github_policy_runner=build_github_policy_processing_runner,
        build_gitlab_policy_runner=build_gitlab_policy_processing_runner,
        publish_gitlab_summary=_publish_gitlab_operational_summary,
    ).run()
