from pathlib import Path

from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.services.intake.sonar_finding_source import (
    SonarFindingSource,
    sonar_issue_to_normalized_finding,
)


class FakeSonarClient:
    def search_open_issues(self) -> list[SonarIssue]:
        return [
            SonarIssue(
                key="AX123",
                rule="python:S1125",
                severity="LOW",
                type="CODE_SMELL",
                status="OPEN",
                message="Replace boolean equality with direct truthiness.",
                component="sample-project:src/service.py",
                project="sample-project",
                file_path="src/service.py",
                line=42,
            )
        ]


def build_issue() -> SonarIssue:
    return SonarIssue(
        key="AX123",
        rule="python:S1125",
        severity="LOW",
        type="CODE_SMELL",
        status="OPEN",
        message="Replace boolean equality with direct truthiness.",
        component="sample-project:src/service.py",
        project="sample-project",
        file_path="src/service.py",
        line=42,
    )


def test_sonar_issue_to_normalized_finding_uses_shared_contract() -> None:
    finding = sonar_issue_to_normalized_finding(build_issue())

    assert finding.finding_id == "AX123"
    assert finding.source_id == "sonarqube"
    assert finding.severity == "low"
    assert finding.repository_path == "src/service.py"
    assert finding.remediation_context.diagnostic_code == "python:S1125"
    assert finding.source_metadata is not None
    assert finding.source_metadata.native_id == "AX123"
    assert finding.source_metadata.attributes["type"] == "CODE_SMELL"


def test_collect_open_findings_returns_raw_issues_and_normalized_collection() -> None:
    result = SonarFindingSource(FakeSonarClient()).collect_open_findings()

    assert len(result.issues) == 1
    assert result.collection.metadata.source_id == "sonarqube"
    assert result.collection.metadata.statistics == {"collected": 1}
    assert result.collection.findings[0].finding_id == "AX123"


def test_collect_fixture_findings_sets_artifact_reference(tmp_path: Path) -> None:
    fixture = tmp_path / "sonar.json"
    fixture.write_text(
        (
            '{"issues":[{"key":"AX123","rule":"python:S1125","severity":"LOW",'
            '"type":"CODE_SMELL","status":"OPEN",'
            '"message":"Replace boolean equality with direct truthiness.",'
            '"component":"sample-project:src/service.py","project":"sample-project",'
            '"line":42}]}'
        ),
        encoding="utf-8",
    )

    result = SonarFindingSource().collect_fixture_findings(fixture)

    assert result.collection.metadata.artifact_reference == str(fixture)
    assert result.collection.findings[0].finding_id == "AX123"
