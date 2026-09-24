from pathlib import Path

import httpx

from zeroone_ops.models.config import SonarQubeConnectionConfig
from zeroone_ops.models.policy import PolicySeverityStateEntry, PolicyState
from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.providers.sonar_client import SonarClient
from zeroone_ops.services.intake.finding_promotion_capacity_service import (
    FindingPromotionCapacityService,
)
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
    assert finding.remediation_context.category == "static_analysis_fix"
    assert finding.remediation_context.diagnostic_code == "python:S1125"
    assert finding.source_metadata is not None
    assert finding.source_metadata.native_id == "AX123"
    assert finding.source_metadata.attributes["type"] == "CODE_SMELL"


def test_collect_open_findings_returns_raw_issues_and_normalized_collection() -> None:
    result = SonarFindingSource(FakeSonarClient()).collect_open_findings()

    assert len(result.issues) == 1
    assert result.collection.metadata.source_id == "sonarqube"
    assert result.collection.metadata.managed_source_ids == ["sonarqube"]
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
    assert result.collection.metadata.managed_source_ids == ["sonarqube"]
    assert result.collection.findings[0].finding_id == "AX123"


def test_promotion_can_select_an_eligible_finding_beyond_page_one() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["p"])
        return httpx.Response(
            200,
            json={
                "paging": {"pageIndex": page, "pageSize": 1, "total": 2},
                "issues": [
                    {
                        "key": str(page),
                        "rule": "python:S1125",
                        "type": "CODE_SMELL",
                        "severity": "MINOR" if page == 1 else "CRITICAL",
                        "status": "OPEN",
                        "message": "Simplify comparison.",
                        "component": "sample-project:src/service.py",
                        "project": "sample-project",
                    }
                ],
            },
        )

    client = SonarClient(
        SonarQubeConnectionConfig(
            url="https://sonarqube.example.com",
            token="token",
            project_key="sample-project",
            page_size=1,
        ),
        http_client=httpx.Client(
            base_url="https://sonarqube.example.com", transport=httpx.MockTransport(handler)
        ),
    )
    collection = SonarFindingSource(client).collect_open_findings().collection
    plan = FindingPromotionCapacityService().plan(
        findings=collection.findings,
        policy_state=PolicyState(
            severity_policy=[PolicySeverityStateEntry(severity="high", enabled=True)]
        ),
        open_work_items=[],
        repository_scope="org/repo",
        max_active_work_items=1,
    )
    assert collection.metadata.managed_source_ids == ["sonarqube"]
    assert plan.decision_for(collection.findings[0]).reason == "severity_disabled"
    assert plan.decision_for(collection.findings[1]).disposition == "promote"
