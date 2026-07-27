"""Application runner.

This module acts as the composition root for the bot workflow.
"""

from __future__ import annotations

import logging
import secrets
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.state import AppState, RunStatus, utc_now
from zeroone_ops.providers.github_policy_client import GitHubPolicyClient
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
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
from zeroone_ops.services.control_plane.work_items.github_finding_sync_service import (
    GitHubFindingSyncResult,
    GitHubFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
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
from zeroone_ops.services.remediation.github_remediation_runner import (
    GitHubRemediationRunner,
)
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


def _build_github_policy_issue_service(
    *,
    repo_root: Path,
    config: AppConfig,
    state: AppState,
) -> GitHubPolicyIssueService:
    """Build provider-local GitHub policy access for another control-plane workflow."""
    return GitHubPolicyIssueService(
        GitHubPolicyClient(load_github_connection_config()),
        policy_view_builder=_build_dashboard_policy_view_builder(
            repo_root=repo_root,
            config=config,
            state=state,
        ),
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
    """Run the legacy GitLab dashboard remediation command."""
    return run_remediation(dry_run=dry_run)


def run_remediation(*, dry_run: bool = False) -> RunSummary:
    """Run remediation for the active platform."""
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
        github_config = load_github_connection_config()
        return GitHubRemediationRunner(
            repo_root=repo_root,
            config=config,
            repository_id=github_config.repository,
            work_item_service=GitHubWorkItemService(GitHubWorkItemClient(github_config)),
            run_state_service=run_state_service,
        ).run(
            record=record,
            active_dry_run=active_dry_run,
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
    """Run the legacy GitLab findings-sync command."""
    return sync_findings(dry_run=dry_run)


def sync_findings(*, dry_run: bool = False) -> RunSummary:
    """Collect normalized findings and project them for the active platform."""
    config = load_config()
    if config.platform == "gitlab":
        return _sync_gitlab_findings(config=config, dry_run=dry_run)
    return _sync_github_findings(config=config, dry_run=dry_run)


def _sync_gitlab_findings(*, config: AppConfig, dry_run: bool) -> RunSummary:
    """Project normalized findings into the GitLab dashboard."""
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
    managed_source_ids = set(collection.finding_collection.metadata.managed_source_ids) or {
        finding.source_id for finding in collection.finding_collection.findings
    }
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


def _sync_github_findings(*, config: AppConfig, dry_run: bool) -> RunSummary:
    """Project policy-promoted normalized findings into GitHub work items."""
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
    intake_service = IssueIntakeService(repo_root=repo_root, config=config)
    collection = intake_service.collect_dashboard_sync_issues(
        dry_run=active_dry_run,
        run_id=run_id,
    )
    if (
        not collection.finding_collection.findings
        and not collection.finding_collection.metadata.managed_source_ids
    ):
        record.status = collection_message_status(collection.message)
        record.updated_at = utc_now()
        state_store.save(state)
        return run_state_service.build_summary(
            run_id=run_id,
            status=record.status,
            message=collection.message,
        )
    github_config = load_github_connection_config()
    policy_state = _build_github_policy_issue_service(
        repo_root=repo_root,
        config=config,
        state=state,
    ).load_policy_state(
        repository_id=github_config.repository,
        persist=not active_dry_run,
    )
    sync_result = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(GitHubWorkItemClient(github_config))
    ).sync(
        repository_id=github_config.repository,
        findings=collection.finding_collection.findings,
        policy_state=policy_state,
        managed_source_ids=set(collection.finding_collection.metadata.managed_source_ids),
        persist=not active_dry_run,
    )
    record.status = collection_message_status("synced")
    record.updated_at = utc_now()
    state_store.save(state)
    prefix = "Dry-run would publish" if active_dry_run else "Published"
    return run_state_service.build_summary(
        run_id=run_id,
        status=record.status,
        message=(
            f"{prefix} {sync_result.promoted_count} "
            "promoted findings as GitHub work items; "
            f"{sync_result.backlog_only_count} findings remain backlog-only.\n"
            "Normalized severities: "
            f"{_format_count_summary(sync_result.normalized_severity_counts)}.\n"
            "Promotion policy: "
            f"enabled={_format_enabled_severities(sync_result.enabled_severities)}; "
            "backlog reasons: "
            f"{_format_count_summary(sync_result.backlog_reason_counts)}."
            + _format_lifecycle_reconciliation(sync_result)
        ),
    )


def _format_count_summary(counts: dict[str, int]) -> str:
    """Render deterministic aggregate counts for one CLI-facing sync summary."""
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _format_enabled_severities(enabled_severities: tuple[str, ...]) -> str:
    """Render the resolved policy severities for one CLI-facing sync summary."""
    return ", ".join(enabled_severities) or "none"


def _format_lifecycle_reconciliation(sync_result: GitHubFindingSyncResult) -> str:
    """Render non-empty policy and stale-item lifecycle reconciliation details."""
    if (
        sync_result.demoted_to_candidate_count == 0
        and sync_result.retained_protected_count == 0
        and sync_result.stale_demoted_to_candidate_count == 0
        and sync_result.stale_retained_protected_count == 0
    ):
        return ""
    lines = []
    if sync_result.demoted_to_candidate_count or sync_result.retained_protected_count:
        lines.append(
            "Policy reconciliation: "
            f"demoted to candidate={sync_result.demoted_to_candidate_count}; "
            f"protected work items retained={sync_result.retained_protected_count}."
        )
    if sync_result.stale_demoted_to_candidate_count or sync_result.stale_retained_protected_count:
        lines.append(
            "Stale finding reconciliation: "
            f"demoted to candidate={sync_result.stale_demoted_to_candidate_count}; "
            "protected work items retained="
            f"{sync_result.stale_retained_protected_count}."
        )
    return "\n" + "\n".join(lines)


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
