"""Issue intake service.

This module fetches SonarQube issues for dashboard inventory sync.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.finding import (
    FindingCollectionMetadata,
    FindingCollectionResult,
    NormalizedFinding,
)
from zeroone_ops.providers.sonar_client import SonarClient
from zeroone_ops.services.intake.sonar_finding_source import (
    SonarFindingSource,
    SonarFindingSourceResult,
)
from zeroone_ops.settings import SettingsError, load_sonarqube_connection_config

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncIssueCollectionResult:
    """Capture normalized SonarQube findings collected for dashboard inventory sync."""

    finding_collection: FindingCollectionResult
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
                finding_collection=_empty_finding_collection(),
                issue_count=0,
                message="No SonarQube fixture path is configured.",
            )
        source_result = SonarFindingSource().collect_fixture_findings(fixture_path)
        issue_count = len(source_result.issues)
        finding_collection = self._existing_findings(source_result)
        if not finding_collection.findings:
            return SyncIssueCollectionResult(
                finding_collection=finding_collection,
                issue_count=issue_count,
                message=f"No dashboard-syncable SonarQube issues found in fixture {fixture_path}.",
            )
        return SyncIssueCollectionResult(
            finding_collection=finding_collection,
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
                finding_collection=_empty_finding_collection(),
                issue_count=0,
                message="No SonarQube issues collected. SonarQube credentials not configured.",
            )

        source_result = SonarFindingSource(sonar_client).collect_open_findings()
        issue_count = len(source_result.issues)
        finding_collection = self._existing_findings(source_result)
        if not finding_collection.findings:
            return SyncIssueCollectionResult(
                finding_collection=finding_collection,
                issue_count=issue_count,
                message="No dashboard-syncable SonarQube issues found.",
            )
        return SyncIssueCollectionResult(
            finding_collection=finding_collection,
            issue_count=issue_count,
            message="",
        )

    def _existing_findings(
        self,
        source_result: SonarFindingSourceResult,
    ) -> FindingCollectionResult:
        """Filter normalized findings to files that exist in the local repository.

        Args:
            source_result: Raw Sonar issues plus normalized findings.

        Returns:
            Only normalized findings whose repository-relative target files exist locally.
        """
        kept_findings: list[NormalizedFinding] = []
        for issue, finding in zip(
            source_result.issues,
            source_result.collection.findings,
            strict=False,
        ):
            if not (self.repo_root / issue.file_path).exists():
                continue
            kept_findings.append(finding)
        return FindingCollectionResult(
            findings=kept_findings,
            metadata=source_result.collection.metadata,
        )


def _empty_finding_collection() -> FindingCollectionResult:
    """Return an empty SonarQube finding collection for intake failures."""
    return FindingCollectionResult(
        findings=[],
        metadata=FindingCollectionMetadata(
            source_id="sonarqube",
            statistics={"collected": 0},
        ),
    )
