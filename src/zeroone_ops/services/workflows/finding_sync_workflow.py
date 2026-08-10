"""Finding-sync workflow composition for GitHub and GitLab."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from zeroone_ops.models.config import AppConfig, GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.state import AppState, RunStatus, utc_now
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
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
from zeroone_ops.services.control_plane.policy.github_policy_issue_service import (
    GitHubPolicyIssueService,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_service import (
    GitLabPolicyIssueService,
)
from zeroone_ops.services.control_plane.work_items.github_finding_sync_service import (
    GitHubFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service import (
    GitLabFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.dashboard.dashboard_policy_view_builder import (
    DashboardPolicyViewBuilder,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.intake.finding_dashboard_sync_service import (
    FindingDashboardSyncService,
)
from zeroone_ops.services.intake.issue_intake import IssueIntakeService, SyncIssueCollectionResult
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.workflows.operational_summary import (
    build_finding_sync_observation,
    format_count_summary,
    format_enabled_severities,
    format_finding_sync_reconciliation,
    format_operational_summary_publication,
)
from zeroone_ops.services.workflows.workflow_run_context import WorkflowRunContext


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


class DashboardPolicyViewBuilderFactory(Protocol):
    """Build a dashboard policy view only for legacy GitLab sync."""

    def __call__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        state: AppState,
    ) -> DashboardPolicyViewBuilder:
        """Build the legacy dashboard policy view."""


class GitHubPolicyIssueServiceBuilder(Protocol):
    """Build GitHub policy access only after GitHub routing is selected."""

    def __call__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        state: AppState,
    ) -> GitHubPolicyIssueService:
        """Build GitHub policy access."""


class GitLabPolicyIssueServiceBuilder(Protocol):
    """Build GitLab policy access only after issue-mode routing is selected."""

    def __call__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        state: AppState,
    ) -> GitLabPolicyIssueService:
        """Build GitLab policy access."""


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


class FindingSyncResult(Protocol):
    """Expose shared provider-local finding-sync result fields."""

    @property
    def promoted_count(self) -> int:
        """Return the promoted finding count."""

    @property
    def backlog_only_count(self) -> int:
        """Return the backlog-only finding count."""

    @property
    def normalized_severity_counts(self) -> dict[str, int]:
        """Return normalized severity counts."""

    @property
    def enabled_severities(self) -> tuple[str, ...]:
        """Return the enabled policy severities."""

    @property
    def backlog_reason_counts(self) -> dict[str, int]:
        """Return backlog counts grouped by reason."""

    @property
    def demoted_to_candidate_count(self) -> int:
        """Return policy-demoted item count."""

    @property
    def retained_protected_count(self) -> int:
        """Return protected policy item count."""

    @property
    def stale_demoted_to_candidate_count(self) -> int:
        """Return stale-demoted item count."""

    @property
    def stale_retained_protected_count(self) -> int:
        """Return protected stale item count."""


class FindingSyncWorkflow:
    """Route normalized findings to the configured control-plane storage."""

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
        build_github_policy_issue_service: GitHubPolicyIssueServiceBuilder,
        build_gitlab_policy_issue_service: GitLabPolicyIssueServiceBuilder,
        publish_github_summary: GitHubSummaryPublisher,
        publish_gitlab_summary: GitLabSummaryPublisher,
    ) -> None:
        """Initialize workflow composition without loading provider settings."""
        self.config = config
        self.dry_run = dry_run
        self.build_run_id = build_run_id
        self.build_context = build_context
        self.is_gitlab_issue_mode = is_gitlab_issue_mode
        self.load_github_config = load_github_config
        self.load_gitlab_config = load_gitlab_config
        self.build_dashboard_policy_view = build_dashboard_policy_view
        self.build_github_policy_issue_service = build_github_policy_issue_service
        self.build_gitlab_policy_issue_service = build_gitlab_policy_issue_service
        self.publish_github_summary = publish_github_summary
        self.publish_gitlab_summary = publish_gitlab_summary

    def run(self) -> RunSummary:
        """Run the explicit provider and control-plane route for this sync."""
        if self.config.platform == "gitlab":
            if self.is_gitlab_issue_mode(self.config):
                return self._run_gitlab_issue_mode()
            return self._run_legacy_gitlab_dashboard()
        return self._run_github_issue_mode()

    def _run_legacy_gitlab_dashboard(self) -> RunSummary:
        """Project findings into the legacy GitLab dashboard without policy state."""
        gitlab_config = self.load_gitlab_config()
        context = self._build_context()
        collection = self._collect(context)
        managed_source_ids = set(collection.finding_collection.metadata.managed_source_ids) or {
            finding.source_id for finding in collection.finding_collection.findings
        }
        if not collection.finding_collection.findings and not managed_source_ids:
            return RunSummary(
                run_id=context.run_id,
                status=_collection_message_status(collection.message),
                message=f"[{self.config.execution_mode}] {collection.message}",
                state_path=context.state_store.path,
            )
        if context.active_dry_run:
            return RunSummary(
                run_id=context.run_id,
                status=_collection_message_status("synced"),
                message=(
                    f"[{self.config.execution_mode}] Dry-run found "
                    f"{len(collection.finding_collection.findings)} "
                    "findings for dashboard sync."
                ),
                state_path=context.state_store.path,
            )

        sync_result = FindingDashboardSyncService(
            DashboardService(
                GitLabDashboardClient(gitlab_config),
                policy_view_builder=self.build_dashboard_policy_view(
                    repo_root=context.repo_root,
                    config=self.config,
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
            status=_collection_message_status("synced"),
            message=(
                f"[{self.config.execution_mode}] Synced {sync_result.synced_count} "
                f"findings to the dashboard. Dashboard: {sync_result.dashboard_issue_url}"
            ),
            state_path=context.state_store.path,
        )

    def _run_github_issue_mode(self) -> RunSummary:
        """Project policy-promoted normalized findings into GitHub work items."""
        context = self._build_context()
        record = context.run_state_service.start_run(context.run_id)
        collection = self._collect(context)
        if (
            not collection.finding_collection.findings
            and not collection.finding_collection.metadata.managed_source_ids
        ):
            record.status = _collection_message_status(collection.message)
            record.updated_at = utc_now()
            context.state_store.save(context.state)
            return context.run_state_service.build_summary(
                run_id=context.run_id,
                status=record.status,
                message=collection.message,
            )

        github_config = self.load_github_config()
        policy_state = self.build_github_policy_issue_service(
            repo_root=context.repo_root,
            config=self.config,
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
            max_active_work_items=self.config.remediation.max_active_work_items,
            persist=not context.active_dry_run,
        )
        summary_publication = (
            self.publish_github_summary(
                github_config=github_config,
                work_item_service=work_item_service,
                latest_finding_sync=build_finding_sync_observation(sync_result),
            )
            if not context.active_dry_run
            else None
        )
        record.status = _collection_message_status("synced")
        record.updated_at = utc_now()
        context.state_store.save(context.state)
        return context.run_state_service.build_summary(
            run_id=context.run_id,
            status=record.status,
            message=self._issue_mode_message(
                sync_result=sync_result,
                provider="GitHub",
                active_dry_run=context.active_dry_run,
                summary_publication=summary_publication,
            ),
        )

    def _run_gitlab_issue_mode(self) -> RunSummary:
        """Project policy-promoted normalized findings into GitLab work items."""
        gitlab_config = self.load_gitlab_config()
        context = self._build_context()
        collection = self._collect(context)
        metadata = collection.finding_collection.metadata
        if not collection.finding_collection.findings and not metadata.managed_source_ids:
            return RunSummary(
                run_id=context.run_id,
                status=_collection_message_status(collection.message),
                message=f"[{self.config.execution_mode}] {collection.message}",
                state_path=context.state_store.path,
            )

        policy_state = self.build_gitlab_policy_issue_service(
            repo_root=context.repo_root,
            config=self.config,
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
            max_active_work_items=self.config.remediation.max_active_work_items,
            persist=not context.active_dry_run,
        )
        summary_publication = (
            self.publish_gitlab_summary(
                gitlab_config=gitlab_config,
                work_item_service=work_item_service,
                latest_finding_sync=build_finding_sync_observation(sync_result),
            )
            if not context.active_dry_run
            else None
        )
        return RunSummary(
            run_id=context.run_id,
            status=RunStatus.SYNCED,
            message=(
                f"[{self.config.execution_mode}] "
                + self._issue_mode_message(
                    sync_result=sync_result,
                    provider="GitLab",
                    active_dry_run=context.active_dry_run,
                    summary_publication=summary_publication,
                )
            ),
            state_path=context.state_store.path,
        )

    def _build_context(self) -> WorkflowRunContext:
        """Build shared repository-local state for the selected route."""
        return self.build_context(
            config=self.config,
            run_id=self.build_run_id(),
            dry_run=self.dry_run,
        )

    def _collect(self, context: WorkflowRunContext) -> SyncIssueCollectionResult:
        """Collect normalized findings without selecting a provider client."""
        return IssueIntakeService(
            repo_root=context.repo_root,
            config=self.config,
        ).collect_dashboard_sync_issues(
            dry_run=context.active_dry_run,
            run_id=context.run_id,
        )

    def _issue_mode_message(
        self,
        *,
        sync_result: FindingSyncResult,
        provider: str,
        active_dry_run: bool,
        summary_publication: (
            GitHubOperationalSummaryPublishResult | GitLabOperationalSummaryPublishResult | None
        ),
    ) -> str:
        """Render the unchanged issue-mode sync result for either provider."""
        promoted_count = sync_result.promoted_count
        backlog_only_count = sync_result.backlog_only_count
        publication_message = (
            (
                f"Dry-run identified {promoted_count} findings eligible under "
                "the configured policy; "
                f"{backlog_only_count} findings are policy-backlog-only.\n"
                "Dry-run does not load existing open work items, so active capacity and "
                "stale-item reconciliation are not included."
            )
            if active_dry_run
            else (
                f"Published {promoted_count} promoted findings as {provider} work items; "
                f"{backlog_only_count} findings remain backlog-only."
            )
        )
        return (
            publication_message
            + "\nNormalized severities: "
            + f"{format_count_summary(sync_result.normalized_severity_counts)}.\n"
            + "Promotion policy: "
            + f"enabled={format_enabled_severities(sync_result.enabled_severities)}; "
            + "backlog reasons: "
            + f"{format_count_summary(sync_result.backlog_reason_counts)}."
            + format_finding_sync_reconciliation(sync_result)
            + format_operational_summary_publication(summary_publication)
        )


def _collection_message_status(message: str) -> RunStatus:
    """Map finding-sync collection outcomes to run statuses."""
    return RunStatus.NO_ISSUE if message != "synced" else RunStatus.SYNCED
