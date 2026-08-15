"""Best-effort derived operational-summary composition."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from zeroone_ops.models.config import GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.state import utc_now
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.github_policy_client import GitHubPolicyClient
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.providers.gitlab_policy_client import GitLabPolicyClient
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient
from zeroone_ops.services.control_plane.overview.github_operational_summary_renderer import (
    GitHubFindingSyncObservation,
)
from zeroone_ops.services.control_plane.overview.github_operational_summary_service import (
    GitHubOperationalSummaryPublishResult,
    GitHubOperationalSummaryService,
)
from zeroone_ops.services.control_plane.overview.github_operational_summary_store import (
    GitHubOperationalSummaryStore,
)
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_service import (
    GitLabOperationalSummaryPublishResult,
    GitLabOperationalSummaryService,
)
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_store import (
    GitLabOperationalSummaryStore,
)
from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    FindingSyncObservation,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_store import (
    GitLabPolicyIssueStore,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.settings import load_gitlab_connection_config

LOGGER = logging.getLogger(__name__)


def publish_github_operational_summary(
    *,
    github_config: GitHubConnectionConfig,
    work_item_service: GitHubWorkItemService,
    latest_finding_sync: GitHubFindingSyncObservation | None,
) -> GitHubOperationalSummaryPublishResult | None:
    """Publish the derived GitHub overview without changing the primary outcome."""
    try:
        issue_client = GitHubPolicyClient(github_config)
        policy_issue = issue_client.find_open_issue(
            repository_id=github_config.repository,
            title="ZeroOne Ops Policy",
            labels=["zeroone-policy"],
        )
        return GitHubOperationalSummaryService(
            store=GitHubOperationalSummaryStore(issue_client)
        ).publish(
            repository_id=github_config.repository,
            work_items=[
                *work_item_service.list_open_work_items(repository_id=github_config.repository),
                *work_item_service.list_closed_work_items(repository_id=github_config.repository),
            ],
            policy_issue_url=policy_issue.web_url if policy_issue is not None else None,
            latest_finding_sync=latest_finding_sync,
        )
    except (GitHubClientError, httpx.HTTPError):
        LOGGER.warning(
            "GitHub operational summary publication failed after a control-plane transition",
            exc_info=True,
        )
        return None


def publish_gitlab_operational_summary(
    *,
    gitlab_config: GitLabConnectionConfig,
    work_item_service: GitLabWorkItemService,
    latest_finding_sync: FindingSyncObservation | None,
) -> GitLabOperationalSummaryPublishResult | None:
    """Publish the derived GitLab overview without changing the primary outcome."""
    try:
        project_id = gitlab_config.project_id
        issue_client = GitLabWorkItemClient(gitlab_config)
        policy_issue = GitLabPolicyIssueStore(
            GitLabPolicyClient(gitlab_config, issue_client=issue_client),
            title="ZeroOne Ops Policy",
            labels=["zeroone-policy"],
        ).find_open_issue(project_id=project_id)
        return GitLabOperationalSummaryService(
            store=GitLabOperationalSummaryStore(issue_client)
        ).publish(
            project_id=project_id,
            work_items=[
                *work_item_service.list_open_work_items(project_id=project_id),
                *work_item_service.list_closed_work_items(project_id=project_id),
            ],
            policy_issue_url=policy_issue.web_url if policy_issue is not None else None,
            latest_finding_sync=latest_finding_sync,
        )
    except (GitLabClientError, httpx.HTTPError):
        LOGGER.warning(
            "GitLab operational summary publication failed after an issue-mode transition",
            exc_info=True,
        )
        return None


def refresh_gitlab_operational_summary() -> str:
    """Refresh the current GitLab issue-mode overview at the composition boundary."""
    gitlab_config = load_gitlab_connection_config()
    publication = publish_gitlab_operational_summary(
        gitlab_config=gitlab_config,
        work_item_service=GitLabWorkItemService(GitLabWorkItemClient(gitlab_config)),
        latest_finding_sync=None,
    )
    return format_operational_summary_publication(publication)


class FindingSyncObservationResult(Protocol):
    """Expose successful finding-sync fields persisted by the overview."""

    @property
    def promoted_count(self) -> int:
        """Return the number of findings promoted into durable coordination."""

    @property
    def backlog_only_count(self) -> int:
        """Return the number of findings deliberately kept backlog-only."""

    @property
    def normalized_severity_counts(self) -> dict[str, int]:
        """Return finding counts by normalized severity."""

    @property
    def backlog_reason_counts(self) -> dict[str, int]:
        """Return backlog-only finding counts by policy reason."""

    @property
    def policy_deferred_count(self) -> int:
        """Return the number of work items closed as policy-deferred."""

    @property
    def policy_reactivated_count(self) -> int:
        """Return the number of deferred work items reopened by policy."""

    @property
    def no_longer_detected_count(self) -> int:
        """Return the number of deferred items completed from inventory."""

    @property
    def projection_warning_count(self) -> int:
        """Return bounded provider projection warnings."""


def build_finding_sync_observation(
    sync_result: FindingSyncObservationResult,
) -> FindingSyncObservation:
    """Build the bounded derived observation from one successful finding sync."""
    return FindingSyncObservation(
        observed_at=utc_now(),
        total_findings=sync_result.promoted_count + sync_result.backlog_only_count,
        promoted_findings=sync_result.promoted_count,
        backlog_only_findings=sync_result.backlog_only_count,
        severity_counts=sync_result.normalized_severity_counts,
        backlog_reason_counts=sync_result.backlog_reason_counts,
        policy_deferred_count=sync_result.policy_deferred_count,
        policy_reactivated_count=sync_result.policy_reactivated_count,
        no_longer_detected_count=sync_result.no_longer_detected_count,
        projection_warning_count=sync_result.projection_warning_count,
    )


def format_operational_summary_publication(
    publication: (
        GitHubOperationalSummaryPublishResult | GitLabOperationalSummaryPublishResult | None
    ),
) -> str:
    """Render optional derived-summary publication output for a CLI summary."""
    if publication is None:
        return ""
    return f"\nOperational summary {publication.action}: {publication.issue.web_url}."


def format_count_summary(counts: dict[str, int]) -> str:
    """Render deterministic aggregate counts for one CLI-facing summary."""
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def format_enabled_severities(enabled_severities: tuple[str, ...]) -> str:
    """Render resolved policy severities for one CLI-facing summary."""
    return ", ".join(enabled_severities) or "none"


class FindingSyncReconciliationResult(Protocol):
    """Expose policy and stale-item reconciliation counts for CLI rendering."""

    @property
    def demoted_to_candidate_count(self) -> int:
        """Return the number of policy-demoted work items."""

    @property
    def retained_protected_count(self) -> int:
        """Return the number of protected policy work items retained."""

    @property
    def stale_demoted_to_candidate_count(self) -> int:
        """Return the number of stale work items demoted to candidates."""

    @property
    def stale_retained_protected_count(self) -> int:
        """Return the number of protected stale work items retained."""

    @property
    def policy_deferred_count(self) -> int:
        """Return the number of work items closed as policy-deferred."""

    @property
    def policy_reactivated_count(self) -> int:
        """Return the number of deferred work items reopened by policy."""

    @property
    def no_longer_detected_count(self) -> int:
        """Return the number of deferred items completed from inventory."""

    @property
    def projection_warning_count(self) -> int:
        """Return bounded provider projection warnings."""


def format_finding_sync_reconciliation(sync_result: FindingSyncReconciliationResult) -> str:
    """Render non-empty policy and stale-item reconciliation details."""
    if (
        sync_result.demoted_to_candidate_count == 0
        and sync_result.retained_protected_count == 0
        and sync_result.stale_demoted_to_candidate_count == 0
        and sync_result.stale_retained_protected_count == 0
        and sync_result.policy_deferred_count == 0
        and sync_result.policy_reactivated_count == 0
        and sync_result.no_longer_detected_count == 0
        and sync_result.projection_warning_count == 0
    ):
        return ""
    lines = []
    if sync_result.demoted_to_candidate_count or sync_result.retained_protected_count:
        lines.append(
            "Policy reconciliation: "
            f"demoted to candidate={sync_result.demoted_to_candidate_count}; "
            f"protected work items retained={sync_result.retained_protected_count}."
        )
    if (
        sync_result.policy_deferred_count
        or sync_result.policy_reactivated_count
        or sync_result.no_longer_detected_count
        or sync_result.projection_warning_count
    ):
        lines.append(
            "Policy state projection: "
            f"deferred={sync_result.policy_deferred_count}; "
            f"reactivated={sync_result.policy_reactivated_count}; "
            f"no longer detected={sync_result.no_longer_detected_count}; "
            f"warnings={sync_result.projection_warning_count}."
        )
    if sync_result.stale_demoted_to_candidate_count or sync_result.stale_retained_protected_count:
        lines.append(
            "Stale finding reconciliation: "
            f"demoted to candidate={sync_result.stale_demoted_to_candidate_count}; "
            "protected work items retained="
            f"{sync_result.stale_retained_protected_count}."
        )
    return "\n" + "\n".join(lines)
