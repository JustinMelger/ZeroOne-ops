"""Application runner.

This module acts as the composition root for the bot workflow.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.state import AppState, FailureDetails, FailureStage, RunStatus, utc_now
from zeroone_ops.providers.github_policy_client import GitHubPolicyClient
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.providers.review.github import GitHubReviewClient
from zeroone_ops.providers.review.gitlab import GitLabReviewClient
from zeroone_ops.providers.review.platform import ChangeRequestReviewPlatformProtocol
from zeroone_ops.services.control_plane.policy.github_policy_issue_service import (
    GitHubPolicyIssueService,
)
from zeroone_ops.services.control_plane.policy.github_policy_processing_runner import (
    GitHubPolicyProcessingRunner,
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
from zeroone_ops.services.dashboard.dashboard_remediation_runner import (
    DashboardRemediationRunner,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.intake.finding_dashboard_sync_service import (
    FindingDashboardSyncService,
)
from zeroone_ops.services.intake.issue_intake import IssueIntakeService
from zeroone_ops.services.review.pipeline.review_runner import ReviewRunner
from zeroone_ops.services.review.state.review_state_service import ReviewStateService
from zeroone_ops.services.shared.run_state_service import (
    RunStateService,
    RunSummary,
)
from zeroone_ops.services.shared.state_store import StateStore
from zeroone_ops.settings import (
    load_config,
    load_current_change_request_number,
    load_current_github_pull_request_head_sha,
    load_current_github_pull_request_number,
    load_github_connection_config,
    load_gitlab_connection_config,
    load_gitlab_project_id_override,
    load_sonarqube_project_key_override,
)

LOGGER = logging.getLogger(__name__)


def _build_run_id() -> str:
    """Build a unique run identifier."""
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def _build_dashboard_policy_view_builder(
    *,
    repo_root: Path,
    config: AppConfig,
    state: AppState,
) -> DashboardPolicyViewBuilder:
    """Build the shared policy-view builder used by control-plane workflows."""
    return DashboardPolicyViewBuilder(
        repo_root=repo_root,
        config=config,
        state=state,
    )


def _build_github_policy_processing_runner(
    *,
    repo_root: Path,
    config: AppConfig,
    state: AppState,
    run_state_service: RunStateService,
) -> GitHubPolicyProcessingRunner:
    """Build the GitHub policy-processing runner and its provider-local transport."""
    github_config = load_github_connection_config()
    return GitHubPolicyProcessingRunner(
        policy_issue_service=GitHubPolicyIssueService(
            GitHubPolicyClient(github_config),
            policy_view_builder=_build_dashboard_policy_view_builder(
                repo_root=repo_root,
                config=config,
                state=state,
            ),
        ),
        run_state_service=run_state_service,
    )


def review(*, dry_run: bool = False) -> RunSummary:
    """Run the merge-request review workflow."""
    config = load_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=load_gitlab_project_id_override(),
        sonarqube_project_key=load_sonarqube_project_key_override(),
    )
    state = state_store.load()
    review_state_service = ReviewStateService(
        state_store=state_store,
        state=state,
        max_prior_review_passes=config.review.max_prior_review_passes,
    )

    run_id = _build_run_id()
    record = review_state_service.start_run(run_id)
    repo_root = Path.cwd()
    active_dry_run = dry_run or config.dry_run
    (
        review_client,
        repository_id,
        current_change_request_number,
        triggered_head_sha,
        dashboard_client,
    ) = _build_review_platform_runtime(config)
    return ReviewRunner(
        repo_root=repo_root,
        config=config,
        review_client=review_client,
        dashboard_client=dashboard_client,
        review_state_service=review_state_service,
    ).run(
        repository_id=repository_id,
        current_change_request_number=current_change_request_number,
        triggered_head_sha=triggered_head_sha,
        record=record,
        run_id=run_id,
        active_dry_run=active_dry_run,
    )


def _build_review_platform_runtime(
    config: AppConfig,
) -> tuple[
    ChangeRequestReviewPlatformProtocol,
    str,
    int | None,
    str | None,
    GitLabDashboardClient | None,
]:
    """Build platform-specific review dependencies for the active review workflow."""
    if config.platform == "github":
        github_config = load_github_connection_config()
        return (
            GitHubReviewClient(github_config),
            github_config.repository,
            load_current_github_pull_request_number(),
            load_current_github_pull_request_head_sha(),
            None,
        )

    gitlab_config = load_gitlab_connection_config()
    return (
        GitLabReviewClient(gitlab_config),
        gitlab_config.project_id,
        load_current_change_request_number(),
        None,
        GitLabDashboardClient(gitlab_config),
    )


def dashboard_remediate(*, dry_run: bool = False) -> RunSummary:
    """Run dashboard-backed remediation."""
    config = load_config()
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
    repo_root = Path.cwd()
    active_dry_run = dry_run or config.dry_run
    if config.platform == "github":
        message = (
            "GitHub remediation intake is not implemented yet. "
            "Phase 5b currently supports GitHub work-item projection only after "
            "a remediation candidate has already been selected."
        )
        return run_state_service.fail_run(
            record=record,
            error_message=message,
            failure=FailureDetails(
                stage=FailureStage.ISSUE_INTAKE,
                message=message,
            ),
        )
    gitlab_config = load_gitlab_connection_config()
    return DashboardRemediationRunner(
        repo_root=repo_root,
        config=config,
        dashboard_service=DashboardService(
            GitLabDashboardClient(gitlab_config),
            policy_view_builder=DashboardPolicyViewBuilder(
                repo_root=repo_root,
                config=config,
                state=state,
            ),
        ),
        run_state_service=run_state_service,
    ).run(
        project_id=gitlab_config.project_id,
        state=state,
        record=record,
        run_id=run_id,
        active_dry_run=active_dry_run,
    )


def sync_dashboard_sonar(*, dry_run: bool = False) -> RunSummary:
    """Sync eligible normalized findings into the dashboard."""
    config = load_config()
    gitlab_config = load_gitlab_connection_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=load_gitlab_project_id_override(),
        sonarqube_project_key=load_sonarqube_project_key_override(),
    )
    state = state_store.load()
    run_id = _build_run_id()
    repo_root = Path.cwd()
    active_dry_run = dry_run or config.dry_run

    intake_service = IssueIntakeService(repo_root=repo_root, config=config)
    collection = intake_service.collect_dashboard_sync_issues(
        dry_run=active_dry_run,
        run_id=run_id,
    )
    managed_source_ids = {
        metadata.source_id for metadata in collection.finding_collection.metadata.input_collections
    } or {finding.source_id for finding in collection.finding_collection.findings}
    if not collection.finding_collection.findings and not managed_source_ids:
        return RunSummary(
            run_id=run_id,
            status=collection_message_status(collection.message),
            message=f"[{config.execution_mode}] {collection.message}",
            state_path=state_store.path,
        )
    if active_dry_run:
        return RunSummary(
            run_id=run_id,
            status=collection_message_status("synced"),
            message=(
                f"[{config.execution_mode}] Dry-run found "
                f"{len(collection.finding_collection.findings)} "
                "findings for dashboard sync."
            ),
            state_path=state_store.path,
        )

    sync_result = FindingDashboardSyncService(
        DashboardService(
            GitLabDashboardClient(gitlab_config),
            policy_view_builder=DashboardPolicyViewBuilder(
                repo_root=repo_root,
                config=config,
                state=state,
            ),
        )
    ).sync(
        project_id=gitlab_config.project_id,
        findings=collection.finding_collection.findings,
        managed_source_ids=managed_source_ids,
    )
    return RunSummary(
        run_id=run_id,
        status=collection_message_status("synced"),
        message=(
            f"[{config.execution_mode}] Synced {sync_result.synced_count} "
            f"findings to the dashboard. Dashboard: {sync_result.dashboard_issue_url}"
        ),
        state_path=state_store.path,
    )


def dashboard_reconcile(*, dry_run: bool = False) -> RunSummary:
    """Run dashboard reconciliation."""
    config = load_config()
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


def dashboard_policy(*, dry_run: bool = False) -> RunSummary:
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
        return _build_github_policy_processing_runner(
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
    return DashboardPolicyProcessingRunner(
        dashboard_service=DashboardService(
            GitLabDashboardClient(gitlab_config),
            policy_view_builder=_build_dashboard_policy_view_builder(
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
