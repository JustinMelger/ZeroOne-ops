"""Source-local SonarQube ingestion into the shared finding contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.finding import (
    FindingCollectionMetadata,
    FindingCollectionResult,
    FindingSourceMetadata,
    NormalizedFinding,
    RemediationContext,
)
from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.providers.sonar_client import SonarClient, load_issues_fixture


@dataclass(frozen=True)
class SonarFindingSourceResult:
    """Capture raw Sonar issues plus their normalized shared finding collection."""

    issues: list[SonarIssue]
    collection: FindingCollectionResult


class SonarFindingSource:
    """Collect SonarQube issues behind the shared finding ingestion contract."""

    def __init__(self, sonar_client: SonarClient | None = None) -> None:
        """Initialize the SonarQube finding source."""
        self.sonar_client = sonar_client

    def collect_open_findings(self) -> SonarFindingSourceResult:
        """Collect open SonarQube issues from the configured API client."""
        if self.sonar_client is None:
            raise RuntimeError("SonarFindingSource requires a SonarClient for API collection.")
        issues = self.sonar_client.search_open_issues()
        return SonarFindingSourceResult(
            issues=issues,
            collection=FindingCollectionResult(
                findings=[sonar_issue_to_normalized_finding(issue) for issue in issues],
                metadata=FindingCollectionMetadata(
                    source_id="sonarqube",
                    statistics={"collected": len(issues)},
                ),
            ),
        )

    def collect_fixture_findings(self, fixture_path: Path) -> SonarFindingSourceResult:
        """Collect SonarQube issues from a local fixture file."""
        issues = load_issues_fixture(fixture_path)
        return SonarFindingSourceResult(
            issues=issues,
            collection=FindingCollectionResult(
                findings=[sonar_issue_to_normalized_finding(issue) for issue in issues],
                metadata=FindingCollectionMetadata(
                    source_id="sonarqube",
                    artifact_reference=str(fixture_path),
                    statistics={"collected": len(issues)},
                ),
            ),
        )


def sonar_issue_to_normalized_finding(issue: SonarIssue) -> NormalizedFinding:
    """Adapt one SonarQube issue into the shared normalized finding shape."""
    return NormalizedFinding(
        finding_id=issue.key,
        source_id="sonarqube",
        severity=issue.automation_severity(),
        title=f"{issue.rule} in {issue.file_path}",
        summary=issue.message,
        repository_path=issue.file_path,
        line_start=issue.line,
        line_end=issue.line,
        remediation_context=RemediationContext(
            category="code_smell_fix",
            diagnostic_code=issue.rule,
        ),
        source_metadata=FindingSourceMetadata(
            native_id=issue.key,
            attributes={
                "rule": issue.rule,
                "type": issue.type,
                "status": issue.status,
                "component": issue.component,
                "project": issue.project,
                "source_severity": issue.source_severity(),
                "effort": issue.effort,
                "tags": list(issue.tags),
                "impacts": [impact.model_dump(mode="json") for impact in issue.impacts],
                "creation_date": (
                    issue.creation_date.isoformat() if issue.creation_date is not None else None
                ),
            },
        ),
    )
