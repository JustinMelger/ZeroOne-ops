"""Issue intake service.

This module fetches SonarQube issues from the configured source and selects one
eligible issue for processing.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.config import AppConfig, GitLabConnectionConfig
from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.models.state import AppState
from zeroone_ops.providers.gitlab_client import GitLabClient
from zeroone_ops.providers.sonar_client import SonarClient, load_issues_fixture
from zeroone_ops.services.intake.issue_eligibility import describe_skip_reasons
from zeroone_ops.services.intake.issue_selector import IssueSelector
from zeroone_ops.services.shared.mr_service import MergeRequestService
from zeroone_ops.settings import (
    SettingsError,
    load_gitlab_connection_config,
    load_sonarqube_connection_config,
)
from zeroone_ops.utils.git import build_issue_branch_name

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class IssueIntakeResult:
    """Capture the result of selecting an issue for a run.

    Attributes:
        selected_issue: The chosen issue, if one was found.
        issue_count: Number of issues fetched from the source.
        message: Human-readable summary when no issue was selected.
    """

    selected_issue: SonarIssue | None
    issue_count: int
    message: str


@dataclass(frozen=True)
class IssueCollectionResult:
    """Capture eligible SonarQube issues for non-remediation consumers."""

    eligible_issues: list[SonarIssue]
    issue_count: int
    message: str


@dataclass(frozen=True)
class SyncIssueCollectionResult:
    """Capture SonarQube issues collected for dashboard inventory sync."""

    issues: list[SonarIssue]
    issue_count: int
    message: str


@dataclass(frozen=True)
class IssueEligibilityResult:
    """Capture eligible issues and why others were skipped."""

    eligible_issues: list[SonarIssue]
    skip_reason_counts: Counter[str]


class IssueIntakeService:
    """Fetch and select one eligible SonarQube issue.

    Args:
        repo_root: Repository root path.
        config: Loaded application configuration.
        selector: Issue selection policy.
    """

    def __init__(
        self,
        repo_root: Path,
        config: AppConfig,
        selector: IssueSelector | None = None,
        merge_request_service: MergeRequestService | None = None,
    ) -> None:
        """Initialize the issue intake service.

        Args:
            repo_root: Repository root path.
            config: Loaded application configuration.
            selector: Optional issue selection policy override.
            merge_request_service: Optional merge request lookup service.
        """
        self.repo_root = repo_root
        self.config = config
        self.selector = selector or IssueSelector(config)
        self.merge_request_service = merge_request_service

    def select_issue(
        self,
        *,
        state: AppState,
        dry_run: bool,
        run_id: str,
    ) -> IssueIntakeResult:
        """Fetch and select one eligible issue.

        Args:
            state: Current application state.
            dry_run: Whether the current run is a dry run.
            run_id: Active run identifier.

        Returns:
            The selected issue result for the run.
        """
        collection = self.collect_eligible_issues(state=state, dry_run=dry_run, run_id=run_id)
        selected_issue = self.selector.select(collection.eligible_issues, state)
        if selected_issue is None:
            return IssueIntakeResult(
                selected_issue=None,
                issue_count=collection.issue_count,
                message=collection.message,
            )
        return IssueIntakeResult(
            selected_issue=selected_issue,
            issue_count=collection.issue_count,
            message="",
        )

    def collect_eligible_issues(
        self,
        *,
        state: AppState,
        dry_run: bool,
        run_id: str,
        allow_remote_duplicate_lookup: bool = True,
    ) -> IssueCollectionResult:
        """Fetch issues and return all eligible candidates without selecting one."""
        if dry_run and self.config.sonarqube.mock_issues_path is not None:
            return self._collect_from_fixture(state=state)
        return self._collect_from_sonarqube(
            state=state,
            run_id=run_id,
            allow_remote_duplicate_lookup=allow_remote_duplicate_lookup,
        )

    def collect_dashboard_sync_issues(
        self,
        *,
        dry_run: bool,
        run_id: str,
    ) -> SyncIssueCollectionResult:
        """Fetch SonarQube issues for dashboard sync without remediation filtering."""
        if dry_run and self.config.sonarqube.mock_issues_path is not None:
            return self._collect_sync_issues_from_fixture()
        return self._collect_sync_issues_from_sonarqube(run_id=run_id)

    def _collect_from_fixture(self, *, state: AppState) -> IssueCollectionResult:
        """Collect eligible issues from a local fixture.

        Args:
            state: Current application state.

        Returns:
            The fixture-backed eligible-issue result.
        """
        fixture_path = self.config.sonarqube.mock_issues_path
        if fixture_path is None:
            return IssueCollectionResult(
                eligible_issues=[],
                issue_count=0,
                message="No SonarQube fixture path is configured.",
            )
        issues = load_issues_fixture(fixture_path)
        issue_count = len(issues)
        eligibility = self._eligible_issues(self._existing_issues(issues), state)
        if not eligibility.eligible_issues:
            return IssueCollectionResult(
                eligible_issues=[],
                issue_count=issue_count,
                message=self._build_no_issue_message(
                    source=f"fixture {fixture_path}",
                    issue_count=issue_count,
                    skip_reason_counts=eligibility.skip_reason_counts,
                ),
            )
        return IssueCollectionResult(
            eligible_issues=eligibility.eligible_issues,
            issue_count=issue_count,
            message="",
        )

    def _collect_sync_issues_from_fixture(self) -> SyncIssueCollectionResult:
        """Collect local-file Sonar issues from a fixture for dashboard sync."""
        fixture_path = self.config.sonarqube.mock_issues_path
        if fixture_path is None:
            return SyncIssueCollectionResult(
                issues=[],
                issue_count=0,
                message="No SonarQube fixture path is configured.",
            )
        issues = load_issues_fixture(fixture_path)
        issue_count = len(issues)
        sync_issues = self._existing_issues(issues)
        if not sync_issues:
            return SyncIssueCollectionResult(
                issues=[],
                issue_count=issue_count,
                message=f"No dashboard-syncable SonarQube issues found in fixture {fixture_path}.",
            )
        return SyncIssueCollectionResult(
            issues=sync_issues,
            issue_count=issue_count,
            message="",
        )

    def _collect_from_sonarqube(
        self,
        *,
        state: AppState,
        run_id: str,
        allow_remote_duplicate_lookup: bool,
    ) -> IssueCollectionResult:
        """Collect eligible issues from the real SonarQube API.

        Args:
            state: Current application state.
            run_id: Active run identifier.
            allow_remote_duplicate_lookup: Whether CI duplicate-MR checks may
                call GitLab during eligibility filtering.

        Returns:
            The SonarQube-backed eligible-issue result.
        """
        try:
            sonar_client = SonarClient(load_sonarqube_connection_config())
        except SettingsError:
            LOGGER.info("skipped SonarQube fetch", extra={"run_id": run_id})
            return IssueCollectionResult(
                eligible_issues=[],
                issue_count=0,
                message="No issue selected. SonarQube credentials not configured.",
            )

        issues = sonar_client.search_open_issues()
        issue_count = len(issues)
        eligibility = self._eligible_issues(
            self._existing_issues(issues),
            state,
            allow_remote_duplicate_lookup=allow_remote_duplicate_lookup,
        )
        if not eligibility.eligible_issues:
            return IssueCollectionResult(
                eligible_issues=[],
                issue_count=issue_count,
                message=self._build_no_issue_message(
                    source=f"{issue_count} open issues",
                    issue_count=issue_count,
                    skip_reason_counts=eligibility.skip_reason_counts,
                ),
            )
        return IssueCollectionResult(
            eligible_issues=eligibility.eligible_issues,
            issue_count=issue_count,
            message="",
        )

    def _collect_sync_issues_from_sonarqube(
        self,
        *,
        run_id: str,
    ) -> SyncIssueCollectionResult:
        """Collect local-file Sonar issues from the API for dashboard sync."""
        try:
            sonar_client = SonarClient(load_sonarqube_connection_config())
        except SettingsError:
            LOGGER.info("skipped SonarQube fetch", extra={"run_id": run_id})
            return SyncIssueCollectionResult(
                issues=[],
                issue_count=0,
                message="No SonarQube issues collected. SonarQube credentials not configured.",
            )

        issues = sonar_client.search_open_issues()
        issue_count = len(issues)
        sync_issues = self._existing_issues(issues)
        if not sync_issues:
            return SyncIssueCollectionResult(
                issues=[],
                issue_count=issue_count,
                message="No dashboard-syncable SonarQube issues found.",
            )
        return SyncIssueCollectionResult(
            issues=sync_issues,
            issue_count=issue_count,
            message="",
        )

    def _existing_issues(self, issues: list[SonarIssue]) -> list[SonarIssue]:
        """Filter issues to files that exist in the local repository.

        Args:
            issues: Candidate issues from SonarQube or a fixture.

        Returns:
            Only issues whose repository-relative target files exist locally.
        """
        return [issue for issue in issues if (self.repo_root / issue.file_path).exists()]

    def _eligible_issues(
        self,
        issues: list[SonarIssue],
        state: AppState,
        *,
        allow_remote_duplicate_lookup: bool = True,
    ) -> IssueEligibilityResult:
        """Filter out issues that are already being handled.

        Args:
            issues: Candidate issues that already map to local files.
            state: Current persisted application state.
            allow_remote_duplicate_lookup: Whether to check GitLab for existing
                open merge requests that already represent a candidate issue.

        Returns:
            Issues that are not already in progress plus skip-reason counts.
        """
        gitlab_config = self._load_gitlab_config() if allow_remote_duplicate_lookup else None
        merge_request_service = self._build_merge_request_service(gitlab_config)
        eligible: list[SonarIssue] = []
        skip_reason_counts: Counter[str] = Counter()
        for issue in issues:
            duplicate_reason = self._duplicate_skip_reason(
                issue,
                state=state,
                gitlab_config=gitlab_config,
                merge_request_service=merge_request_service,
            )
            if duplicate_reason is not None:
                skip_reason_counts[duplicate_reason] += 1
                LOGGER.info(
                    "skipped issue during intake",
                    extra={
                        "issue_key": issue.key,
                        "file_path": issue.file_path,
                        "reason": duplicate_reason,
                    },
                )
                continue
            selector_reason = self.selector.skip_reason(issue, state)
            if selector_reason is not None:
                skip_reason_counts[selector_reason] += 1
                LOGGER.info(
                    "skipped issue during intake",
                    extra={
                        "issue_key": issue.key,
                        "file_path": issue.file_path,
                        "reason": selector_reason,
                    },
                )
                continue
            eligible.append(issue)
        return IssueEligibilityResult(
            eligible_issues=eligible,
            skip_reason_counts=skip_reason_counts,
        )

    def _duplicate_skip_reason(
        self,
        issue: SonarIssue,
        *,
        state: AppState,
        gitlab_config: GitLabConnectionConfig | None,
        merge_request_service: MergeRequestService | None,
    ) -> str | None:
        """Return why an issue is already represented by active bot work.

        Args:
            issue: Candidate SonarQube issue.
            state: Current persisted application state.
            gitlab_config: Loaded GitLab connection config when available.
            merge_request_service: Merge request lookup service when available.

        Returns:
            A duplicate-skip reason, or ``None`` when the issue is not in progress.
        """
        issue_state = state.issues.get(issue.key)
        if issue_state is not None and issue_state.status in {
            "selected",
            "analyzing",
            "fix_generated",
            "mr_created",
        }:
            return "in_progress_state"
        if (
            self.config.execution_mode != "ci"
            or gitlab_config is None
            or merge_request_service is None
        ):
            return None
        branch_name = build_issue_branch_name(
            branch_prefix=self.config.branch_prefix,
            issue_key=issue.key,
            file_path=issue.file_path,
        )
        existing_mr = merge_request_service.find_open(
            project_id=gitlab_config.project_id,
            source_branch=branch_name,
            target_branch=self.config.gitlab.target_branch,
        )
        if existing_mr is None:
            return None
        return "open_merge_request"

    def _load_gitlab_config(self) -> GitLabConnectionConfig | None:
        """Load GitLab config when CI duplicate detection needs it."""
        if self.config.execution_mode != "ci":
            return None
        try:
            return load_gitlab_connection_config()
        except SettingsError:
            return None

    def _build_merge_request_service(
        self,
        gitlab_config: GitLabConnectionConfig | None,
    ) -> MergeRequestService | None:
        """Build a merge request lookup service when GitLab config is available."""
        if self.merge_request_service is not None:
            return self.merge_request_service
        if gitlab_config is None:
            return None
        return MergeRequestService(GitLabClient(gitlab_config))

    def _build_no_issue_message(
        self,
        *,
        source: str,
        issue_count: int,
        skip_reason_counts: Counter[str],
    ) -> str:
        """Build a no-issue summary that explains why intake produced nothing.

        Args:
            source: Human-readable issue source description.
            issue_count: Total number of fetched issues.
            skip_reason_counts: Counts by stable skip-reason code.

        Returns:
            A summary suitable for the final run output.
        """
        summary = f"No eligible SonarQube issue found in {source}."
        if issue_count == 0:
            return summary
        skip_summary = describe_skip_reasons(dict(skip_reason_counts))
        if not skip_summary:
            return summary
        return f"{summary} Skipped {skip_summary}."
