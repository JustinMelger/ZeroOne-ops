"""Application runner.

This module acts as the composition root for the bot workflow.
"""

from __future__ import annotations

import secrets
from dataclasses import replace
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.state import FailureDetails, FailureStage, RunStatus, utc_now
from zeroone_ops.providers.github_client import GitHubClient
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.providers.review.gitlab import GitLabReviewClient
from zeroone_ops.services.control_plane.policy.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
)
from zeroone_ops.services.control_plane.work_items.github_finding_sync_service import (
    GitHubFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lifecycle_service import (
    GitHubWorkItemLifecycleService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service import (
    GitLabFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lifecycle_service import (
    GitLabWorkItemLifecycleService,
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
from zeroone_ops.services.dashboard.dashboard_policy_processing_runner import (
    DashboardPolicyProcessingRunner,
)
from zeroone_ops.services.dashboard.dashboard_policy_view_builder import (
    DashboardPolicyViewBuilder,
)
from zeroone_ops.services.dashboard.dashboard_reconciliation_runner import (
    DashboardReconciliationRunner,
)
from zeroone_ops.services.dashboard.dashboard_recovery_runner import (
    DashboardRecoveryRunner,
)
from zeroone_ops.services.dashboard.dashboard_recovery_service import DashboardRecoveryService
from zeroone_ops.services.dashboard.dashboard_remediation_runner import (
    DashboardRemediationRunner,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.intake.finding_dashboard_sync_service import (
    FindingDashboardSyncService,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)
from zeroone_ops.services.intake.issue_intake import IssueIntakeService
from zeroone_ops.services.remediation.github_remediation_runner import (
    GitHubRemediationRunner,
)
from zeroone_ops.services.remediation.gitlab_remediation_runner import (
    GitLabRemediationRunner,
)
from zeroone_ops.services.review.pipeline.review_runner import ReviewRunner
from zeroone_ops.services.review.state.review_state_service import ReviewStateService
from zeroone_ops.services.shared.run_state_service import (
    RunStateService,
    RunSummary,
)
from zeroone_ops.services.shared.state_store import StateStore
from zeroone_ops.services.workflows.gitlab_issue_control_plane_workflow import (
    GitLabIssueControlPlaneWorkflow,
)
from zeroone_ops.services.workflows.operational_summary import (
    build_finding_sync_observation as _build_finding_sync_observation,
)
from zeroone_ops.services.workflows.operational_summary import (
    format_count_summary as _format_count_summary,
)
from zeroone_ops.services.workflows.operational_summary import (
    format_enabled_severities as _format_enabled_severities,
)
from zeroone_ops.services.workflows.operational_summary import (
    format_finding_sync_reconciliation as _format_finding_sync_reconciliation,
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
    if _gitlab_issue_mode_is_active(config):
        return _run_gitlab_issue_remediation(
            config=config,
            dry_run=dry_run,
            publish_operational_summary=publish_operational_summary,
        )
    context = build_workflow_run_context(
        config=config,
        run_id=_build_run_id(),
        dry_run=dry_run,
    )
    record = context.run_state_service.start_run(context.run_id)
    if config.platform == "github":
        github_config = load_github_connection_config()
        work_item_service = GitHubWorkItemService(GitHubWorkItemClient(github_config))
        summary = GitHubRemediationRunner(
            repo_root=context.repo_root,
            config=config,
            repository_id=github_config.repository,
            work_item_service=work_item_service,
            run_state_service=context.run_state_service,
        ).run(
            record=record,
            active_dry_run=context.active_dry_run,
        )
        if context.active_dry_run or summary.status == RunStatus.NO_ISSUE:
            return summary
        publication = _publish_github_operational_summary(
            github_config=github_config,
            work_item_service=work_item_service,
            latest_finding_sync=None,
        )
        return replace(
            summary,
            message=summary.message + _format_operational_summary_publication(publication),
        )
    gitlab_config = load_gitlab_connection_config()
    return DashboardRemediationRunner(
        repo_root=context.repo_root,
        config=config,
        dashboard_service=DashboardService(
            GitLabDashboardClient(gitlab_config),
            policy_view_builder=DashboardPolicyViewBuilder(
                repo_root=context.repo_root,
                config=config,
                state=context.state,
            ),
        ),
        run_state_service=context.run_state_service,
    ).run(
        project_id=gitlab_config.project_id,
        state=context.state,
        record=record,
        run_id=context.run_id,
        active_dry_run=context.active_dry_run,
    )


def _run_gitlab_issue_remediation(
    *,
    config: AppConfig,
    dry_run: bool,
    publish_operational_summary: bool = True,
) -> RunSummary:
    """Run one GitLab issue-mode remediation through the shared execution lifecycle."""
    context = build_workflow_run_context(
        config=config,
        run_id=_build_run_id(),
        dry_run=dry_run,
    )
    record = context.run_state_service.start_run(context.run_id)
    gitlab_config = load_gitlab_connection_config()
    work_item_service = GitLabWorkItemService(GitLabWorkItemClient(gitlab_config))
    summary = GitLabRemediationRunner(
        repo_root=context.repo_root,
        config=config,
        project_id=gitlab_config.project_id,
        work_item_service=work_item_service,
        run_state_service=context.run_state_service,
    ).run(
        record=record,
        active_dry_run=context.active_dry_run,
    )
    if (
        context.active_dry_run
        or summary.status == RunStatus.NO_ISSUE
        or not publish_operational_summary
    ):
        return summary
    publication = _publish_gitlab_operational_summary(
        gitlab_config=gitlab_config,
        work_item_service=work_item_service,
        latest_finding_sync=None,
    )
    return replace(
        summary,
        message=summary.message + _format_operational_summary_publication(publication),
    )


def sync_dashboard_sonar(*, dry_run: bool = False) -> RunSummary:
    """Run the legacy GitLab findings-sync command."""
    return sync_findings(dry_run=dry_run)


def sync_findings(*, dry_run: bool = False) -> RunSummary:
    """Collect normalized findings and project them for the active platform."""
    config = load_config()
    if config.platform == "gitlab":
        if _gitlab_issue_mode_is_active(config):
            return _sync_gitlab_issue_findings(config=config, dry_run=dry_run)
        return _sync_gitlab_findings(config=config, dry_run=dry_run)
    return _sync_github_findings(config=config, dry_run=dry_run)


def _sync_gitlab_findings(*, config: AppConfig, dry_run: bool) -> RunSummary:
    """Project normalized findings into the GitLab dashboard."""
    gitlab_config = load_gitlab_connection_config()
    context = build_workflow_run_context(
        config=config,
        run_id=_build_run_id(),
        dry_run=dry_run,
    )

    intake_service = IssueIntakeService(repo_root=context.repo_root, config=config)
    collection = intake_service.collect_dashboard_sync_issues(
        dry_run=context.active_dry_run,
        run_id=context.run_id,
    )
    managed_source_ids = set(collection.finding_collection.metadata.managed_source_ids) or {
        finding.source_id for finding in collection.finding_collection.findings
    }
    if not collection.finding_collection.findings and not managed_source_ids:
        return RunSummary(
            run_id=context.run_id,
            status=collection_message_status(collection.message),
            message=f"[{config.execution_mode}] {collection.message}",
            state_path=context.state_store.path,
        )
    if context.active_dry_run:
        return RunSummary(
            run_id=context.run_id,
            status=collection_message_status("synced"),
            message=(
                f"[{config.execution_mode}] Dry-run found "
                f"{len(collection.finding_collection.findings)} "
                "findings for dashboard sync."
            ),
            state_path=context.state_store.path,
        )

    sync_result = FindingDashboardSyncService(
        DashboardService(
            GitLabDashboardClient(gitlab_config),
            policy_view_builder=DashboardPolicyViewBuilder(
                repo_root=context.repo_root,
                config=config,
                state=context.state,
            ),
        )
    ).sync(
        project_id=gitlab_config.project_id,
        findings=collection.finding_collection.findings,
        managed_source_ids=managed_source_ids,
    )
    return RunSummary(
        run_id=context.run_id,
        status=collection_message_status("synced"),
        message=(
            f"[{config.execution_mode}] Synced {sync_result.synced_count} "
            f"findings to the dashboard. Dashboard: {sync_result.dashboard_issue_url}"
        ),
        state_path=context.state_store.path,
    )


def _sync_github_findings(*, config: AppConfig, dry_run: bool) -> RunSummary:
    """Project policy-promoted normalized findings into GitHub work items."""
    context = build_workflow_run_context(
        config=config,
        run_id=_build_run_id(),
        dry_run=dry_run,
    )
    record = context.run_state_service.start_run(context.run_id)
    intake_service = IssueIntakeService(repo_root=context.repo_root, config=config)
    collection = intake_service.collect_dashboard_sync_issues(
        dry_run=context.active_dry_run,
        run_id=context.run_id,
    )
    if (
        not collection.finding_collection.findings
        and not collection.finding_collection.metadata.managed_source_ids
    ):
        record.status = collection_message_status(collection.message)
        record.updated_at = utc_now()
        context.state_store.save(context.state)
        return context.run_state_service.build_summary(
            run_id=context.run_id,
            status=record.status,
            message=collection.message,
        )
    github_config = load_github_connection_config()
    policy_state = build_github_policy_issue_service(
        repo_root=context.repo_root,
        config=config,
        state=context.state,
    ).load_policy_state(
        repository_id=github_config.repository,
        persist=not context.active_dry_run,
    )
    work_item_service = GitHubWorkItemService(GitHubWorkItemClient(github_config))
    sync_result = GitHubFindingSyncService(work_item_service=work_item_service).sync(
        repository_id=github_config.repository,
        findings=collection.finding_collection.findings,
        policy_state=policy_state,
        managed_source_ids=set(collection.finding_collection.metadata.managed_source_ids),
        max_active_work_items=config.remediation.max_active_work_items,
        persist=not context.active_dry_run,
    )
    summary_publication = (
        _publish_github_operational_summary(
            github_config=github_config,
            work_item_service=work_item_service,
            latest_finding_sync=_build_finding_sync_observation(sync_result),
        )
        if not context.active_dry_run
        else None
    )
    record.status = collection_message_status("synced")
    record.updated_at = utc_now()
    context.state_store.save(context.state)
    publication_message = (
        (
            f"Dry-run identified {sync_result.promoted_count} findings eligible under "
            "the configured policy; "
            f"{sync_result.backlog_only_count} findings are policy-backlog-only.\n"
            "Dry-run does not load existing open work items, so active capacity and "
            "stale-item reconciliation are not included."
        )
        if context.active_dry_run
        else (
            f"Published {sync_result.promoted_count} promoted findings as GitHub work items; "
            f"{sync_result.backlog_only_count} findings remain backlog-only."
        )
    )
    return context.run_state_service.build_summary(
        run_id=context.run_id,
        status=record.status,
        message=(
            publication_message + "\n"
            "Normalized severities: "
            f"{_format_count_summary(sync_result.normalized_severity_counts)}.\n"
            "Promotion policy: "
            f"enabled={_format_enabled_severities(sync_result.enabled_severities)}; "
            "backlog reasons: "
            f"{_format_count_summary(sync_result.backlog_reason_counts)}."
            + _format_finding_sync_reconciliation(sync_result)
            + _format_operational_summary_publication(summary_publication)
        ),
    )


def _sync_gitlab_issue_findings(*, config: AppConfig, dry_run: bool) -> RunSummary:
    """Project policy-promoted normalized findings into GitLab work-item issues."""
    gitlab_config = load_gitlab_connection_config()
    context = build_workflow_run_context(
        config=config,
        run_id=_build_run_id(),
        dry_run=dry_run,
    )
    intake_service = IssueIntakeService(repo_root=context.repo_root, config=config)
    collection = intake_service.collect_dashboard_sync_issues(
        dry_run=context.active_dry_run,
        run_id=context.run_id,
    )
    metadata = collection.finding_collection.metadata
    if not collection.finding_collection.findings and not metadata.managed_source_ids:
        return RunSummary(
            run_id=context.run_id,
            status=collection_message_status(collection.message),
            message=f"[{config.execution_mode}] {collection.message}",
            state_path=context.state_store.path,
        )
    policy_state = build_gitlab_policy_issue_service(
        repo_root=context.repo_root,
        config=config,
        state=context.state,
    ).load_policy_state(
        project_id=gitlab_config.project_id,
        persist=not context.active_dry_run,
    )
    work_item_service = GitLabWorkItemService(GitLabWorkItemClient(gitlab_config))
    sync_result = GitLabFindingSyncService(work_item_service=work_item_service).sync(
        project_id=gitlab_config.project_id,
        findings=collection.finding_collection.findings,
        policy_state=policy_state,
        managed_source_ids=set(metadata.managed_source_ids),
        max_active_work_items=config.remediation.max_active_work_items,
        persist=not context.active_dry_run,
    )
    summary_publication = (
        _publish_gitlab_operational_summary(
            gitlab_config=gitlab_config,
            work_item_service=work_item_service,
            latest_finding_sync=_build_finding_sync_observation(sync_result),
        )
        if not context.active_dry_run
        else None
    )
    publication_message = (
        (
            f"Dry-run identified {sync_result.promoted_count} findings eligible under "
            "the configured policy; "
            f"{sync_result.backlog_only_count} findings are policy-backlog-only.\n"
            "Dry-run does not load existing open work items, so active capacity and "
            "stale-item reconciliation are not included."
        )
        if context.active_dry_run
        else (
            f"Published {sync_result.promoted_count} promoted findings as GitLab work items; "
            f"{sync_result.backlog_only_count} findings remain backlog-only."
        )
    )
    return RunSummary(
        run_id=context.run_id,
        status=RunStatus.SYNCED,
        message=(
            f"[{config.execution_mode}] {publication_message}\n"
            "Normalized severities: "
            f"{_format_count_summary(sync_result.normalized_severity_counts)}.\n"
            "Promotion policy: "
            f"enabled={_format_enabled_severities(sync_result.enabled_severities)}; "
            "backlog reasons: "
            f"{_format_count_summary(sync_result.backlog_reason_counts)}."
            + _format_finding_sync_reconciliation(sync_result)
            + _format_operational_summary_publication(summary_publication)
        ),
        state_path=context.state_store.path,
    )


def dashboard_reconcile(*, dry_run: bool = False) -> RunSummary:
    """Run the legacy GitLab dashboard reconciliation command."""
    config = load_config()
    if _gitlab_issue_mode_is_active(config):
        return _issue_mode_workflow_unavailable_summary(
            config=config,
            workflow="dashboard reconciliation",
        )
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
    gitlab_config = load_gitlab_connection_config()
    return DashboardReconciliationRunner(
        config=config,
        dashboard_service=DashboardService(
            GitLabDashboardClient(gitlab_config),
            policy_view_builder=DashboardPolicyViewBuilder(
                repo_root=Path.cwd(),
                config=config,
                state=state,
            ),
        ),
        review_client=GitLabReviewClient(gitlab_config),
        run_state_service=run_state_service,
    ).run(
        project_id=gitlab_config.project_id,
        record=record,
        run_id=run_id,
        active_dry_run=active_dry_run,
        execution_mode=config.execution_mode,
    )


def sync_work_item_status(*, dry_run: bool = False) -> RunSummary:
    """Reconcile remediation work-item lifecycle state for the active platform."""
    config = load_config()
    if _gitlab_issue_mode_is_active(config):
        return _sync_gitlab_work_item_status(config=config, dry_run=dry_run)
    if config.platform == "gitlab":
        return dashboard_reconcile(dry_run=dry_run)
    return _sync_github_work_item_status(config=config, dry_run=dry_run)


def recover_work_item(
    *,
    dry_run: bool = False,
    publish_operational_summary: bool = True,
) -> RunSummary:
    """Process provider-local remediation recovery commands."""
    config = load_config()
    if _gitlab_issue_mode_is_active(config):
        return _recover_gitlab_issue_work_items(
            config=config,
            dry_run=dry_run,
            publish_operational_summary=publish_operational_summary,
        )
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
    if config.platform == "gitlab":
        gitlab_config = load_gitlab_connection_config()
        return DashboardRecoveryRunner(
            recovery_service=DashboardRecoveryService(
                dashboard_service=DashboardService(
                    GitLabDashboardClient(gitlab_config),
                    policy_view_builder=DashboardPolicyViewBuilder(
                        repo_root=Path.cwd(),
                        config=config,
                        state=state,
                    ),
                )
            ),
            run_state_service=run_state_service,
        ).run(
            project_id=gitlab_config.project_id,
            record=record,
            active_dry_run=active_dry_run,
            execution_mode=config.execution_mode,
        )
    issue_number = load_current_github_issue_number()
    comment_id = load_current_github_issue_comment_id()
    if issue_number is None or comment_id is None:
        message = "GitHub recovery requires an issue_comment workflow event."
        return run_state_service.fail_run(
            record=record,
            error_message=message,
            failure=FailureDetails(stage=FailureStage.DASHBOARD_UPDATE, message=message),
        )
    github_config = load_github_connection_config()
    recovery_runner, work_item_service = build_github_work_item_recovery_runner(
        run_state_service=run_state_service
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
        policy_state = build_github_policy_issue_service(
            repo_root=Path.cwd(),
            config=config,
            state=state,
        ).load_policy_state(
            repository_id=github_config.repository,
            persist=not active_dry_run,
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
        active_dry_run=active_dry_run,
        execution_mode=config.execution_mode,
    )
    if active_dry_run or summary.status != RunStatus.SYNCED:
        return summary
    publication = _publish_github_operational_summary(
        github_config=github_config,
        work_item_service=work_item_service,
        latest_finding_sync=None,
    )
    return replace(
        summary,
        message=summary.message + _format_operational_summary_publication(publication),
    )


def _recover_gitlab_issue_work_items(
    *,
    config: AppConfig,
    dry_run: bool,
    publish_operational_summary: bool = True,
) -> RunSummary:
    """Poll open GitLab work-item issues for authorized recovery notes."""
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=load_gitlab_project_id_override(),
        sonarqube_project_key=load_sonarqube_project_key_override(),
    )
    state = state_store.load()
    run_state_service = RunStateService(config=config, state_store=state_store, state=state)
    record = run_state_service.start_run(_build_run_id())
    active_dry_run = dry_run or config.dry_run
    gitlab_config = load_gitlab_connection_config()
    work_item_client = GitLabWorkItemClient(gitlab_config)
    work_item_service = GitLabWorkItemService(work_item_client)
    policy_state = build_gitlab_policy_issue_service(
        repo_root=Path.cwd(),
        config=config,
        state=state,
    ).load_policy_state(
        project_id=gitlab_config.project_id,
        persist=not active_dry_run,
    )
    summary = GitLabWorkItemRecoveryRunner(
        recovery_service=GitLabWorkItemRecoveryService(
            note_client=work_item_client,
            note_authorization_service=GitLabPolicyNoteAuthorizationService(work_item_client),
            work_item_service=work_item_service,
        ),
        work_item_service=work_item_service,
        policy_service=FindingWorkflowPolicyService(),
        run_state_service=run_state_service,
    ).run(
        project_id=gitlab_config.project_id,
        policy_state=policy_state,
        record=record,
        active_dry_run=active_dry_run,
        execution_mode=config.execution_mode,
    )
    if active_dry_run or summary.status != RunStatus.SYNCED or not publish_operational_summary:
        return summary
    publication = _publish_gitlab_operational_summary(
        gitlab_config=gitlab_config,
        work_item_service=work_item_service,
        latest_finding_sync=None,
    )
    return replace(
        summary,
        message=summary.message + _format_operational_summary_publication(publication),
    )


def _sync_github_work_item_status(*, config: AppConfig, dry_run: bool) -> RunSummary:
    """Converge GitHub work-item state from PR state and current finding inventory."""
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
    if not active_dry_run and config.execution_mode != "ci":
        message = (
            "GitHub work-item lifecycle execution is only supported in CI mode. "
            "Use --dry-run locally."
        )
        return run_state_service.fail_run(
            record=record,
            error_message=message,
            failure=FailureDetails(stage=FailureStage.RECONCILIATION, message=message),
        )

    github_config = load_github_connection_config()
    work_item_service = GitHubWorkItemService(GitHubWorkItemClient(github_config))
    lifecycle_result = GitHubWorkItemLifecycleService(
        work_item_service=work_item_service,
        change_request_client=GitHubClient(github_config),
    ).reconcile(
        repository_id=github_config.repository,
        now=utc_now(),
        persist=not active_dry_run,
    )
    summary_publication = (
        _publish_github_operational_summary(
            github_config=github_config,
            work_item_service=work_item_service,
            latest_finding_sync=None,
        )
        if not active_dry_run
        else None
    )
    record.status = RunStatus.RECONCILED
    record.updated_at = utc_now()
    state_store.save(state)
    prefix = "Dry-run would reconcile" if active_dry_run else "Reconciled"
    return run_state_service.build_summary(
        run_id=run_id,
        status=record.status,
        message=(
            f"{prefix} GitHub remediation work items: "
            f"stale claims recovered={lifecycle_result.recovered_stale_claim_count}; "
            f"completed={lifecycle_result.completed_count}; "
            f"closed native issues={lifecycle_result.closed_issue_count}; "
            f"blocked={lifecycle_result.blocked_count}; "
            f"in progress={lifecycle_result.in_progress_count}."
            + _format_operational_summary_publication(summary_publication)
        ),
    )


def _sync_gitlab_work_item_status(*, config: AppConfig, dry_run: bool) -> RunSummary:
    """Converge GitLab issue-mode work-item state from linked merge-request state."""
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
    if not active_dry_run and config.execution_mode != "ci":
        message = (
            "GitLab work-item lifecycle execution is only supported in CI mode. "
            "Use --dry-run locally."
        )
        return run_state_service.fail_run(
            record=record,
            error_message=message,
            failure=FailureDetails(stage=FailureStage.RECONCILIATION, message=message),
        )
    gitlab_config = load_gitlab_connection_config()
    work_item_service = GitLabWorkItemService(GitLabWorkItemClient(gitlab_config))
    lifecycle_result = GitLabWorkItemLifecycleService(
        work_item_service=work_item_service,
        change_request_client=GitLabReviewClient(gitlab_config),
    ).reconcile(
        project_id=gitlab_config.project_id,
        now=utc_now(),
        persist=not active_dry_run,
    )
    summary_publication = (
        _publish_gitlab_operational_summary(
            gitlab_config=gitlab_config,
            work_item_service=work_item_service,
            latest_finding_sync=None,
        )
        if not active_dry_run
        else None
    )
    record.status = RunStatus.RECONCILED
    record.updated_at = utc_now()
    state_store.save(state)
    prefix = "Dry-run would reconcile" if active_dry_run else "Reconciled"
    return run_state_service.build_summary(
        run_id=run_id,
        status=record.status,
        message=(
            f"{prefix} GitLab remediation work items: "
            f"stale claims recovered={lifecycle_result.recovered_stale_claim_count}; "
            f"completed={lifecycle_result.completed_count}; "
            f"closed native issues={lifecycle_result.closed_issue_count}; "
            f"blocked={lifecycle_result.blocked_count}; "
            f"in progress={lifecycle_result.in_progress_count}."
            + _format_operational_summary_publication(summary_publication)
        ),
    )


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


def collection_message_status(message: str) -> RunStatus:
    """Map dashboard-sync outcomes to run statuses."""
    return RunStatus.NO_ISSUE if message != "synced" else RunStatus.SYNCED


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
