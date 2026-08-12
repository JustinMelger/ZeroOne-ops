"""Issue intake service.

This module fetches SonarQube issues for dashboard inventory sync.
"""

from __future__ import annotations

import json
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
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)
from zeroone_ops.services.intake.sarif_finding_source import SarifFindingSource
from zeroone_ops.services.intake.sonar_finding_source import SonarFindingSource
from zeroone_ops.settings import SettingsError, load_sonarqube_connection_config

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncIssueCollectionResult:
    """Capture normalized findings collected for dashboard inventory sync."""

    finding_collection: FindingCollectionResult
    issue_count: int
    message: str


class IssueIntakeService:
    """Fetch normalized findings for dashboard inventory sync.

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
        self.workflow_policy_service = FindingWorkflowPolicyService()

    def collect_dashboard_sync_issues(
        self,
        *,
        dry_run: bool,
        run_id: str,
    ) -> SyncIssueCollectionResult:
        """Fetch dashboard-syncable normalized findings without remediation filtering."""
        source_collections = self._source_collections(dry_run=dry_run, run_id=run_id)
        if not source_collections:
            return SyncIssueCollectionResult(
                finding_collection=_empty_finding_collection(),
                issue_count=0,
                message="No configured finding sources collected dashboard-syncable findings.",
            )
        finding_collection = self._merge_collections(source_collections)
        finding_collection = self._existing_findings(finding_collection)
        if not finding_collection.findings:
            return SyncIssueCollectionResult(
                finding_collection=finding_collection,
                issue_count=int(finding_collection.metadata.statistics.get("collected", 0)),
                message="No dashboard-syncable findings found.",
            )
        return SyncIssueCollectionResult(
            finding_collection=finding_collection,
            issue_count=int(finding_collection.metadata.statistics.get("collected", 0)),
            message="",
        )

    def _source_collections(
        self,
        *,
        dry_run: bool,
        run_id: str,
    ) -> list[FindingCollectionResult]:
        """Return raw finding collections from configured dashboard sources."""
        collections: list[FindingCollectionResult] = []
        if dry_run and self.config.sonarqube.mock_issues_path is not None:
            collections.append(
                SonarFindingSource()
                .collect_fixture_findings(self.config.sonarqube.mock_issues_path)
                .collection
            )
        else:
            sonar_collection = self._live_sonarqube_collection(run_id=run_id)
            if sonar_collection is not None:
                collections.append(sonar_collection)
        for artifact in self.config.sarif.artifacts:
            try:
                collections.append(
                    SarifFindingSource().collect_artifact_findings(
                        artifact.path,
                        declared_source_id=artifact.source_id,
                    )
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
                LOGGER.warning(
                    "skipped unavailable SARIF artifact",
                    extra={
                        "artifact_path": str(artifact.path),
                        "source_id": artifact.source_id,
                        "error_type": type(error).__name__,
                    },
                )
                collections.append(
                    _unavailable_sarif_artifact_collection(artifact.path, artifact.source_id)
                )
        return collections

    def _live_sonarqube_collection(self, *, run_id: str) -> FindingCollectionResult | None:
        """Return the live SonarQube finding collection when credentials are configured."""
        try:
            sonar_client = SonarClient(load_sonarqube_connection_config())
        except SettingsError:
            LOGGER.info("skipped SonarQube fetch", extra={"run_id": run_id})
            return None
        return SonarFindingSource(sonar_client).collect_open_findings().collection

    def _merge_collections(
        self,
        source_collections: list[FindingCollectionResult],
    ) -> FindingCollectionResult:
        """Merge independent source collections without applying cross-source dedupe."""
        findings: list[NormalizedFinding] = []
        warnings: list[str] = []
        statistics: dict[str, int] = {}
        managed_source_ids: set[str] = set()
        for collection in source_collections:
            findings.extend(collection.findings)
            warnings.extend(collection.metadata.warnings)
            managed_source_ids.update(collection.metadata.managed_source_ids)
            for key, value in collection.metadata.statistics.items():
                statistics[key] = statistics.get(key, 0) + value
        return FindingCollectionResult(
            findings=findings,
            metadata=FindingCollectionMetadata(
                source_id="dashboard_sync",
                managed_source_ids=sorted(managed_source_ids),
                input_collections=[collection.metadata for collection in source_collections],
                warnings=warnings,
                statistics=statistics,
            ),
        )

    def _existing_findings(
        self,
        finding_collection: FindingCollectionResult,
    ) -> FindingCollectionResult:
        """Filter normalized findings to files that exist in the local repository.

        Args:
            finding_collection: Normalized findings collected for dashboard sync.

        Returns:
            Only normalized findings whose repository-relative target files exist locally.
        """
        kept_findings: list[NormalizedFinding] = []
        locally_excluded_sources: set[str] = set()
        for finding in finding_collection.findings:
            resolved_path = self._resolve_repository_path(finding.repository_path)
            if resolved_path is None or not resolved_path.exists():
                locally_excluded_sources.add(finding.source_id)
                continue
            decision = self.workflow_policy_service.decide(finding=finding)
            if decision.disposition != "queue_candidate":
                continue
            kept_findings.append(finding)
        managed_source_ids = [
            source_id
            for source_id in finding_collection.metadata.managed_source_ids
            if source_id not in locally_excluded_sources
        ]
        return FindingCollectionResult(
            findings=kept_findings,
            metadata=finding_collection.metadata.model_copy(
                update={"managed_source_ids": managed_source_ids}
            ),
        )

    def _resolve_repository_path(self, repository_path: str) -> Path | None:
        """Return a contained repository path or ``None`` when it escapes the repo root."""
        candidate = self.repo_root / repository_path
        try:
            resolved_repo_root = self.repo_root.resolve()
            resolved_candidate = candidate.resolve()
        except OSError:
            return None
        if (
            resolved_candidate != resolved_repo_root
            and resolved_repo_root not in resolved_candidate.parents
        ):
            return None
        return resolved_candidate


def _empty_finding_collection() -> FindingCollectionResult:
    """Return an empty finding collection for intake failures."""
    return FindingCollectionResult(
        findings=[],
        metadata=FindingCollectionMetadata(
            source_id="dashboard_sync",
            statistics={"collected": 0},
        ),
    )


def _unavailable_sarif_artifact_collection(
    artifact_path: Path,
    source_id: str,
) -> FindingCollectionResult:
    """Record an unavailable artifact without claiming stale-reconciliation ownership."""
    return FindingCollectionResult(
        metadata=FindingCollectionMetadata(
            source_id=source_id,
            artifact_reference=str(artifact_path),
            warnings=[f"SARIF artifact for source {source_id!r} was unavailable."],
            statistics={"unavailable_artifacts": 1},
        )
    )
