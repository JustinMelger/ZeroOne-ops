"""Issue intake service.

This module fetches SonarQube issues from the configured source and selects one
eligible issue for processing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.config import AppConfig, GitLabConnectionConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import AppState
from ai_sonar_bot.providers.gitlab_client import GitLabClient
from ai_sonar_bot.providers.sonar_client import SonarClient, load_issues_fixture
from ai_sonar_bot.services.issue_selector import IssueSelector
from ai_sonar_bot.services.mr_service import MergeRequestService
from ai_sonar_bot.settings import (
    SettingsError,
    load_gitlab_connection_config,
    load_sonarqube_connection_config,
)
from ai_sonar_bot.utils.git import build_issue_branch_name

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
        if dry_run and self.config.mock_sonar_issues_path is not None:
            return self._select_from_fixture(state=state)
        return self._select_from_sonarqube(state=state, run_id=run_id)

    def _select_from_fixture(self, *, state: AppState) -> IssueIntakeResult:
        """Select an issue from a local fixture.

        Args:
            state: Current application state.

        Returns:
            The fixture-backed issue intake result.
        """
        fixture_path = self.config.mock_sonar_issues_path
        if fixture_path is None:
            return IssueIntakeResult(
                selected_issue=None,
                issue_count=0,
                message="No SonarQube fixture path is configured.",
            )
        issues = load_issues_fixture(fixture_path)
        issue_count = len(issues)
        selected_issue = self.selector.select(
            self._eligible_issues(self._existing_issues(issues), state),
            state,
        )
        if selected_issue is None:
            return IssueIntakeResult(
                selected_issue=None,
                issue_count=issue_count,
                message=(f"No eligible SonarQube issue found in fixture {fixture_path}."),
            )
        return IssueIntakeResult(selected_issue=selected_issue, issue_count=issue_count, message="")

    def _select_from_sonarqube(self, *, state: AppState, run_id: str) -> IssueIntakeResult:
        """Select an issue from the real SonarQube API.

        Args:
            state: Current application state.
            run_id: Active run identifier.

        Returns:
            The SonarQube-backed issue intake result.
        """
        try:
            sonar_client = SonarClient(load_sonarqube_connection_config())
        except SettingsError:
            LOGGER.info("skipped SonarQube fetch", extra={"run_id": run_id})
            return IssueIntakeResult(
                selected_issue=None,
                issue_count=0,
                message="No issue selected. SonarQube credentials not configured.",
            )

        issues = sonar_client.search_open_issues()
        issue_count = len(issues)
        selected_issue = self.selector.select(
            self._eligible_issues(self._existing_issues(issues), state),
            state,
        )
        if selected_issue is None:
            return IssueIntakeResult(
                selected_issue=None,
                issue_count=issue_count,
                message=f"No eligible SonarQube issue found among {issue_count} open issues.",
            )
        return IssueIntakeResult(selected_issue=selected_issue, issue_count=issue_count, message="")

    def _existing_issues(self, issues: list[SonarIssue]) -> list[SonarIssue]:
        """Filter issues to files that exist in the local repository.

        Args:
            issues: Candidate issues from SonarQube or a fixture.

        Returns:
            Only issues whose repository-relative target files exist locally.
        """
        return [issue for issue in issues if (self.repo_root / issue.file_path).exists()]

    def _eligible_issues(self, issues: list[SonarIssue], state: AppState) -> list[SonarIssue]:
        """Filter out issues that are already being handled.

        Args:
            issues: Candidate issues that already map to local files.
            state: Current persisted application state.

        Returns:
            Issues that are not already in progress.
        """
        gitlab_config = self._load_gitlab_config()
        merge_request_service = self._build_merge_request_service(gitlab_config)
        eligible: list[SonarIssue] = []
        for issue in issues:
            if self._is_issue_already_in_progress(
                issue,
                state=state,
                gitlab_config=gitlab_config,
                merge_request_service=merge_request_service,
            ):
                continue
            eligible.append(issue)
        return eligible

    def _is_issue_already_in_progress(
        self,
        issue: SonarIssue,
        *,
        state: AppState,
        gitlab_config: GitLabConnectionConfig | None,
        merge_request_service: MergeRequestService | None,
    ) -> bool:
        """Return whether an issue is already represented by active bot work.

        Args:
            issue: Candidate SonarQube issue.
            state: Current persisted application state.
            gitlab_config: Loaded GitLab connection config when available.
            merge_request_service: Merge request lookup service when available.

        Returns:
            ``True`` when the issue should be skipped for this run.
        """
        issue_state = state.issues.get(issue.key)
        if issue_state is not None and issue_state.status in {
            "selected",
            "analyzing",
            "fix_generated",
            "mr_created",
        }:
            return True
        if (
            self.config.execution_mode != "ci"
            or gitlab_config is None
            or merge_request_service is None
        ):
            return False
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
        return existing_mr is not None

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
