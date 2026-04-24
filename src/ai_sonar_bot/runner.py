"""Application runner.

This module acts as the composition root for the bot workflow.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from ai_sonar_bot.models.state import RemediationExclusionState, RunStatus
from ai_sonar_bot.providers.gitlab_dashboard_client import GitLabDashboardClient
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient
from ai_sonar_bot.services.dashboard_reconciliation_runner import (
    DashboardReconciliationRunner,
)
from ai_sonar_bot.services.dashboard_remediation_runner import (
    DashboardRemediationRunner,
)
from ai_sonar_bot.services.dashboard_service import DashboardService
from ai_sonar_bot.services.issue_intake import IssueIntakeService
from ai_sonar_bot.services.remediation_exclusion_service import RemediationExclusionService
from ai_sonar_bot.services.review_runner import ReviewRunner
from ai_sonar_bot.services.review_state_service import ReviewStateService
from ai_sonar_bot.services.run_state_service import RunStateService, RunSummary
from ai_sonar_bot.services.sonar_dashboard_sync_service import SonarDashboardSyncService
from ai_sonar_bot.services.state_store import StateStore
from ai_sonar_bot.settings import (
    load_config,
    load_gitlab_connection_config,
    load_gitlab_project_id_override,
    load_sonarqube_project_key_override,
)

LOGGER = logging.getLogger(__name__)


def _build_run_id() -> str:
    """Build a unique run identifier."""
    from ai_sonar_bot.models.state import utc_now

    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def _load_exclusion_service() -> tuple[RemediationExclusionService, Path]:
    config = load_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=load_gitlab_project_id_override(),
        sonarqube_project_key=load_sonarqube_project_key_override(),
    )
    state = state_store.load()
    return RemediationExclusionService(state_store=state_store, state=state), state_store.path


def list_remediation_exclusions() -> tuple[list[RemediationExclusionState], Path]:
    """Return persisted remediation exclusions and their state path."""
    service, state_path = _load_exclusion_service()
    return service.list_exclusions(), state_path


def summarize_remediation_exclusions() -> tuple[dict[str, int], Path]:
    """Return grouped remediation exclusion counts and their state path."""
    service, state_path = _load_exclusion_service()
    return service.summarize_exclusions_by_source(), state_path


def add_remediation_exclusion(
    *,
    source: str,
    issue_key: str,
    reason: str,
    scope: str | None = None,
    updated_by: str | None = None,
) -> tuple[RemediationExclusionState, bool, Path]:
    """Persist one remediation exclusion and return the resulting record."""
    service, state_path = _load_exclusion_service()
    result = service.add_exclusion(
        source=source,
        issue_key=issue_key,
        reason=reason,
        scope=scope,
        updated_by=updated_by,
    )
    if result.exclusion is None:
        raise RuntimeError("Exclusion add unexpectedly produced no record.")
    return result.exclusion, result.created, state_path


def remove_remediation_exclusion(
    *,
    source: str,
    issue_key: str,
    scope: str | None = None,
) -> tuple[RemediationExclusionState | None, bool, Path]:
    """Remove one remediation exclusion when present."""
    service, state_path = _load_exclusion_service()
    result = service.remove_exclusion(source=source, issue_key=issue_key, scope=scope)
    return result.exclusion, result.removed, state_path


def review(*, dry_run: bool = False) -> RunSummary:
    """Run the merge-request review workflow."""
    config = load_config()
    gitlab_config = load_gitlab_connection_config()
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
        gitlab_project_id=load_gitlab_project_id_override(),
        sonarqube_project_key=load_sonarqube_project_key_override(),
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
        gitlab_project_id=load_gitlab_project_id_override(),
        sonarqube_project_key=load_sonarqube_project_key_override(),
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
