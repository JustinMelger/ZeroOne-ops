"""Application runner.

This module acts as the composition root for the bot workflow.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

from ai_sonar_bot.models.state import RunStatus
from ai_sonar_bot.providers.gitlab_dashboard_client import GitLabDashboardClient
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient
from ai_sonar_bot.services.dashboard_reconciliation_runner import (
    DashboardReconciliationRunner,
)
from ai_sonar_bot.services.dashboard_remediation_runner import (
    DashboardRemediationRunner,
)
from ai_sonar_bot.services.dashboard_service import DashboardService
from ai_sonar_bot.services.execution_service import ExecutionService
from ai_sonar_bot.services.issue_intake import IssueIntakeService
from ai_sonar_bot.services.remediation_execution_adapter import (
    remediation_work_item_to_execution_target,
    sonar_issue_to_work_item,
)
from ai_sonar_bot.services.review_runner import ReviewRunner
from ai_sonar_bot.services.review_state_service import ReviewStateService
from ai_sonar_bot.services.run_state_service import RunStateService, RunSummary
from ai_sonar_bot.services.sonar_dashboard_sync_service import SonarDashboardSyncService
from ai_sonar_bot.services.state_store import StateStore
from ai_sonar_bot.settings import load_config, load_gitlab_connection_config

LOGGER = logging.getLogger(__name__)


def _build_run_id() -> str:
    """Build a unique run identifier."""
    from ai_sonar_bot.models.state import utc_now

    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def _project_id_from_env() -> str | None:
    """Read the GitLab project ID override from the environment."""
    return os.environ.get("GITLAB_PROJECT_ID")


def _sonarqube_key_from_env() -> str | None:
    """Read the SonarQube project key override from the environment."""
    return os.environ.get("SONARQUBE_PROJECT_KEY")


def run(*, dry_run: bool = False) -> RunSummary:
    """Run the bot.

    Args:
        dry_run: Whether to execute in dry-run mode.

    Returns:
        A summary of the run result.
    """
    config = load_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=_project_id_from_env(),
        sonarqube_project_key=_sonarqube_key_from_env(),
    )
    state = state_store.load()
    run_state_service = RunStateService(config=config, state_store=state_store, state=state)

    run_id = _build_run_id()
    record = run_state_service.start_run(run_id)
    repo_root = Path.cwd()
    active_dry_run = dry_run or config.dry_run

    intake_result = IssueIntakeService(
        repo_root=repo_root,
        config=config,
    ).select_issue(
        state=state,
        dry_run=active_dry_run,
        run_id=run_id,
    )

    if intake_result.selected_issue is None:
        return run_state_service.finish_no_issue(
            record=record,
            message=intake_result.message,
            issue_count=intake_result.issue_count,
        )

    attempt_count = run_state_service.mark_selected(
        record=record,
        issue_key=intake_result.selected_issue.key,
    )
    work_item = sonar_issue_to_work_item(intake_result.selected_issue)

    execution_result = ExecutionService(repo_root=repo_root, config=config).execute(
        selected_issue=remediation_work_item_to_execution_target(work_item),
        dry_run=active_dry_run,
    )

    record.branch_name = execution_result.branch_name
    record.commit_sha = execution_result.commit_sha

    if execution_result.failure is not None:
        return run_state_service.fail_issue(
            record=record,
            issue_key=intake_result.selected_issue.key,
            attempt_count=attempt_count + (0 if active_dry_run else 1),
            error_message=execution_result.failure.message,
            failure=execution_result.failure,
        )
    if (
        execution_result.final_status is not None
        and execution_result.final_status.value == "rejected"
    ):
        return run_state_service.reject_issue(
            record=record,
            issue_key=intake_result.selected_issue.key,
            attempt_count=attempt_count + 1,
            branch_name=execution_result.branch_name,
            message=execution_result.status_message,
        )

    if execution_result.commit_sha is not None:
        run_state_service.mark_fix_generated(
            record=record,
            issue_key=intake_result.selected_issue.key,
            attempt_count=attempt_count + 1,
            branch_name=execution_result.branch_name,
            commit_sha=execution_result.commit_sha,
        )

    if execution_result.mr_url is not None:
        run_state_service.mark_mr_created(
            record=record,
            issue_key=intake_result.selected_issue.key,
            attempt_count=attempt_count + 1,
            branch_name=execution_result.branch_name,
            mr_url=execution_result.mr_url,
        )

    run_state_service.finish_success(record=record)
    message = (
        f"Selected SonarQube issue {work_item.source_ref} in "
        f"{work_item.file_path} "
        f"({work_item.rule_id}, {work_item.severity}). "
        f"{execution_result.status_message}"
    )
    return run_state_service.build_summary(
        run_id=record.run_id,
        status=record.status,
        message=message,
        issue_key=intake_result.selected_issue.key,
        branch_name=record.branch_name,
        commit_sha=record.commit_sha,
        mr_url=execution_result.mr_url,
        mr_action=execution_result.mr_action,
    )


def review(*, dry_run: bool = False) -> RunSummary:
    """Run the merge-request review workflow."""
    config = load_config()
    gitlab_config = load_gitlab_connection_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=_project_id_from_env(),
        sonarqube_project_key=_sonarqube_key_from_env(),
    )
    state = state_store.load()
    review_state_service = ReviewStateService(state_store=state_store, state=state)

    run_id = _build_run_id()
    record = review_state_service.start_run(run_id)
    repo_root = Path.cwd()
    active_dry_run = dry_run or config.dry_run
    return ReviewRunner(
        repo_root=repo_root,
        config=config,
        review_client=GitLabReviewClient(gitlab_config),
        dashboard_client=GitLabDashboardClient(gitlab_config),
        review_state_service=review_state_service,
    ).run(
        project_id=gitlab_config.project_id,
        record=record,
        run_id=run_id,
        active_dry_run=active_dry_run,
    )


def dashboard_remediate(*, dry_run: bool = False) -> RunSummary:
    """Run dashboard-backed remediation."""
    config = load_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=_project_id_from_env(),
        sonarqube_project_key=_sonarqube_key_from_env(),
    )
    state = state_store.load()
    run_state_service = RunStateService(config=config, state_store=state_store, state=state)

    run_id = _build_run_id()
    record = run_state_service.start_run(run_id)
    repo_root = Path.cwd()
    active_dry_run = dry_run or config.dry_run
    gitlab_config = load_gitlab_connection_config()
    return DashboardRemediationRunner(
        repo_root=repo_root,
        config=config,
        dashboard_service=DashboardService(GitLabDashboardClient(gitlab_config)),
        run_state_service=run_state_service,
    ).run(
        project_id=gitlab_config.project_id,
        state=state,
        record=record,
        run_id=run_id,
        active_dry_run=active_dry_run,
    )


def sync_dashboard_sonar(*, dry_run: bool = False) -> RunSummary:
    """Sync eligible SonarQube issues into the dashboard."""
    config = load_config()
    gitlab_config = load_gitlab_connection_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=_project_id_from_env(),
        sonarqube_project_key=_sonarqube_key_from_env(),
    )
    state = state_store.load()
    run_id = _build_run_id()
    repo_root = Path.cwd()
    active_dry_run = dry_run or config.dry_run

    intake_service = IssueIntakeService(repo_root=repo_root, config=config)
    collection = intake_service.collect_eligible_issues(
        state=state,
        dry_run=active_dry_run,
        run_id=run_id,
        allow_remote_duplicate_lookup=not active_dry_run,
    )
    if not collection.eligible_issues:
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
                f"[{config.execution_mode}] Dry-run found {len(collection.eligible_issues)} "
                "eligible SonarQube issues for dashboard sync."
            ),
            state_path=state_store.path,
        )

    sync_result = SonarDashboardSyncService(
        DashboardService(GitLabDashboardClient(gitlab_config))
    ).sync(
        project_id=gitlab_config.project_id,
        issues=collection.eligible_issues,
    )
    return RunSummary(
        run_id=run_id,
        status=collection_message_status("synced"),
        message=(
            f"[{config.execution_mode}] Synced {sync_result.synced_count} eligible "
            f"SonarQube issues to the dashboard. Dashboard: {sync_result.dashboard_issue_url}"
        ),
        state_path=state_store.path,
    )


def dashboard_reconcile(*, dry_run: bool = False) -> RunSummary:
    """Run dashboard reconciliation."""
    config = load_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=_project_id_from_env(),
        sonarqube_project_key=_sonarqube_key_from_env(),
    )
    state = state_store.load()
    run_state_service = RunStateService(config=config, state_store=state_store, state=state)

    run_id = _build_run_id()
    record = run_state_service.start_run(run_id)
    active_dry_run = dry_run or config.dry_run
    gitlab_config = load_gitlab_connection_config()
    return DashboardReconciliationRunner(
        dashboard_service=DashboardService(GitLabDashboardClient(gitlab_config)),
        review_client=GitLabReviewClient(gitlab_config),
        run_state_service=run_state_service,
    ).run(
        project_id=gitlab_config.project_id,
        record=record,
        run_id=run_id,
        active_dry_run=active_dry_run,
        execution_mode=config.execution_mode,
    )


def collection_message_status(message: str) -> RunStatus:
    """Map dashboard-sync outcomes to run statuses."""
    return RunStatus.NO_ISSUE if message != "synced" else RunStatus.SYNCED
