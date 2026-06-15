"""Issue intake service.

This module fetches SonarQube issues for dashboard inventory sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.providers.sonar_client import SonarClient, load_issues_fixture
from zeroone_ops.settings import SettingsError, load_sonarqube_connection_config

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncIssueCollectionResult:
    """Capture SonarQube issues collected for dashboard inventory sync."""

    issues: list[SonarIssue]
    issue_count: int
    message: str


class IssueIntakeService:
    """Fetch SonarQube issues for dashboard inventory sync.

    Args:
        repo_root: Repository root path.
        config: Loaded application configuration.
    """

    def __init__(
        self,
        repo_root: Path,
        config: AppConfig,
    ) -> None:
        """Initialize the issue intake service.

        Args:
            repo_root: Repository root path.
            config: Loaded application configuration.
        """
        self.repo_root = repo_root
        self.config = config

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
