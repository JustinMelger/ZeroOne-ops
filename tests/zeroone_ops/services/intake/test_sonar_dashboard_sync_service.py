from pathlib import Path

from pytest import LogCaptureFixture

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
    ReviewConfig,
    SarifArtifactConfig,
    SarifConfig,
    SonarQubeConfig,
    StateConfig,
)
from zeroone_ops.models.dashboard import DashboardDocument, DashboardItem, DashboardSection
from zeroone_ops.models.finding import (
    FindingCollectionMetadata,
    FindingCollectionResult,
    NormalizedFinding,
)
from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.services.intake.finding_dashboard_sync_service import (
    FindingDashboardSyncService,
)
from zeroone_ops.services.intake.issue_intake import IssueIntakeService
from zeroone_ops.services.intake.sonar_finding_source import sonar_issue_to_normalized_finding


class FakeDashboardDocument:
    def __init__(self, issue_url: str) -> None:
        self.issue_url = issue_url


class FakeDashboardService:
    def __init__(self, document: DashboardDocument | None = None) -> None:
        self.items = []
        self.document = document

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        assert project_id == "123"
        if self.document is None:
            self.document = DashboardDocument(
                issue_id=11,
                issue_iid=11,
                issue_url="https://gitlab.example.com/group/project/-/issues/11",
                title="AI Code Ops Work Queue",
                sections=[],
            )
        return self.document

    def upsert_items(self, *, project_id: str, items: list) -> FakeDashboardDocument:
        assert project_id == "123"
        self.items = items
        return FakeDashboardDocument("https://gitlab.example.com/group/project/-/issues/11")


def test_sync_normalizes_sonar_issues_into_dashboard_items() -> None:
    dashboard_service = FakeDashboardService()
    service = FindingDashboardSyncService(dashboard_service)

    result = service.sync(
        project_id="123",
        findings=[sonar_issue_to_normalized_finding(build_issue())],
    )

    assert result.synced_count == 1
    assert result.dashboard_issue_url is not None
    assert dashboard_service.items[0].id == "sonar:AX123"
    assert dashboard_service.items[0].source == "sonarqube"
    assert dashboard_service.items[0].status == "open"
    assert dashboard_service.items[0].upstream_active is True
    assert dashboard_service.items[0].rule == "python:S1125"
    assert dashboard_service.items[0].source_severity == "LOW"
    assert dashboard_service.items[0].automation_severity == "low"
    assert dashboard_service.items[0].severity == "low"


def test_intake_bridge_can_expose_normalized_sonar_findings_without_switching_downstream(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    config = AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(bootstrap_severities=["LOW"], analysis=AnalysisConfig()),
        review=ReviewConfig(),
        gitlab=GitLabConfig(target_branch="main"),
        sonarqube=SonarQubeConfig(),
        state=StateConfig(path=repo_root / ".zeroone-ops-state.json"),
    )

    fixture = repo_root / "sonar.json"
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
    source_file = repo_root / "src" / "service.py"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("value = flag == True\n", encoding="utf-8")
    config.sonarqube.mock_issues_path = fixture

    collection = IssueIntakeService(
        repo_root=repo_root,
        config=config,
    ).collect_dashboard_sync_issues(dry_run=True, run_id="run-1")

    assert len(collection.finding_collection.findings) == 1
    assert collection.finding_collection.findings[0].finding_id == "AX123"


def test_intake_merge_preserves_unmanaged_source_collection(tmp_path: Path) -> None:
    config = AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(bootstrap_severities=["LOW"], analysis=AnalysisConfig()),
        review=ReviewConfig(),
        gitlab=GitLabConfig(target_branch="main"),
        sonarqube=SonarQubeConfig(),
        state=StateConfig(path=tmp_path / ".zeroone-ops-state.json"),
    )
    service = IssueIntakeService(repo_root=tmp_path, config=config)

    merged = service._merge_collections(
        [
            FindingCollectionResult(
                metadata=FindingCollectionMetadata(
                    source_id="ruff-sarif",
                    warnings=["SARIF input was partial."],
                )
            )
        ]
    )

    assert merged.metadata.managed_source_ids == []


def test_intake_skips_unavailable_sarif_artifact_without_claiming_source_ownership(
    tmp_path: Path,
    caplog: LogCaptureFixture,
) -> None:
    config = AppConfig(
        base_branch="main",
        remediation=RemediationConfig(target_branch="main"),
        gitlab=GitLabConfig(target_branch="main"),
        sarif=SarifConfig(
            artifacts=[
                SarifArtifactConfig(
                    path=tmp_path / "artifacts" / "missing.sarif",
                    source_id="ruff-sarif",
                )
            ]
        ),
    )

    collection = IssueIntakeService(
        repo_root=tmp_path,
        config=config,
    ).collect_dashboard_sync_issues(dry_run=True, run_id="run-1")

    metadata = collection.finding_collection.metadata
    assert metadata.managed_source_ids == []
    assert metadata.input_collections[0].source_id == "ruff-sarif"
    assert metadata.input_collections[0].artifact_reference == str(
        tmp_path / "artifacts" / "missing.sarif"
    )
    assert metadata.warnings == ["SARIF artifact for source 'ruff-sarif' was unavailable."]
    assert metadata.statistics == {"unavailable_artifacts": 1}
    assert "skipped unavailable SARIF artifact" in caplog.text


def test_intake_bridge_rejects_findings_that_escape_repo_root(tmp_path: Path) -> None:
    repo_root = tmp_path
    config = AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(bootstrap_severities=["LOW"], analysis=AnalysisConfig()),
        review=ReviewConfig(),
        gitlab=GitLabConfig(target_branch="main"),
        sonarqube=SonarQubeConfig(),
        state=StateConfig(path=repo_root / ".zeroone-ops-state.json"),
    )

    fixture = repo_root / "sonar.json"
    fixture.write_text(
        (
            '{"issues":[{"key":"AX123","rule":"python:S1125","severity":"LOW",'
            '"type":"CODE_SMELL","status":"OPEN",'
            '"message":"Replace boolean equality with direct truthiness.",'
            '"component":"sample-project:../outside.py","project":"sample-project",'
            '"line":42}]}'
        ),
        encoding="utf-8",
    )
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "service.py").write_text("value = flag == True\n", encoding="utf-8")
    config.sonarqube.mock_issues_path = fixture

    collection = IssueIntakeService(
        repo_root=repo_root,
        config=config,
    ).collect_dashboard_sync_issues(dry_run=True, run_id="run-1")

    assert collection.finding_collection.findings == []


def test_intake_bridge_keeps_input_collection_provenance_for_mixed_sources(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    config = AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(bootstrap_severities=["LOW"], analysis=AnalysisConfig()),
        review=ReviewConfig(),
        gitlab=GitLabConfig(target_branch="main"),
        sonarqube=SonarQubeConfig(),
        state=StateConfig(path=repo_root / ".zeroone-ops-state.json"),
    )

    fixture = repo_root / "sonar.json"
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
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "service.py").write_text("value = flag == True\n", encoding="utf-8")
    (repo_root / "artifacts").mkdir(parents=True, exist_ok=True)
    (repo_root / "artifacts" / "ruff.sarif").write_text(
        """
        {
          "version": "2.1.0",
          "runs": [
            {
              "tool": {
                "driver": {
                  "name": "Ruff",
                  "rules": [
                    {
                      "id": "E712",
                      "shortDescription": {"text": "Avoid equality comparisons to True"}
                    }
                  ]
                }
              },
              "results": [
                {
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {"text": "Use direct truthiness instead of == True."},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/service.py"},
                        "region": {"startLine": 1, "endLine": 1}
                      }
                    }
                  ]
                }
              ]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    config.sonarqube.mock_issues_path = fixture
    config.sarif.artifacts = [
        SarifArtifactConfig(
            path=repo_root / "artifacts" / "ruff.sarif",
            source_id="ruff-sarif",
            severity_mapping={"warning": "low"},
        ),
        SarifArtifactConfig(
            path=repo_root / "artifacts" / "missing.sarif",
            source_id="mypy-sarif",
        ),
    ]

    collection = IssueIntakeService(
        repo_root=repo_root,
        config=config,
    ).collect_dashboard_sync_issues(dry_run=True, run_id="run-1")

    assert len(collection.finding_collection.metadata.input_collections) == 3
    assert collection.finding_collection.metadata.managed_source_ids == [
        "ruff-sarif",
        "sonarqube",
    ]
    assert collection.finding_collection.metadata.input_collections[0].source_id == "sonarqube"
    assert collection.finding_collection.metadata.input_collections[0].artifact_reference == str(
        fixture
    )
    assert collection.finding_collection.metadata.input_collections[1].source_id == "ruff-sarif"
    assert collection.finding_collection.metadata.input_collections[1].artifact_reference == str(
        repo_root / "artifacts" / "ruff.sarif"
    )
    assert [
        finding.severity
        for finding in collection.finding_collection.findings
        if finding.source_id == "ruff-sarif"
    ] == ["low"]
    assert collection.finding_collection.metadata.input_collections[2].source_id == "mypy-sarif"
    assert collection.finding_collection.metadata.input_collections[2].artifact_reference == str(
        repo_root / "artifacts" / "missing.sarif"
    )
    assert collection.finding_collection.metadata.warnings == [
        "SARIF artifact for source 'mypy-sarif' was unavailable."
    ]


def test_intake_bridge_does_not_mark_locally_filtered_sources_as_fully_managed(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    config = AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(bootstrap_severities=["LOW"], analysis=AnalysisConfig()),
        review=ReviewConfig(),
        gitlab=GitLabConfig(target_branch="main"),
        sonarqube=SonarQubeConfig(),
        state=StateConfig(path=repo_root / ".zeroone-ops-state.json"),
    )

    fixture = repo_root / "sonar.json"
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
    (repo_root / "src").mkdir(parents=True, exist_ok=True)
    (repo_root / "src" / "service.py").write_text("value = flag == True\n", encoding="utf-8")
    (repo_root / "artifacts").mkdir(parents=True, exist_ok=True)
    (repo_root / "artifacts" / "ruff.sarif").write_text(
        """
        {
          "version": "2.1.0",
          "runs": [
            {
              "tool": {
                "driver": {
                  "name": "Ruff",
                  "rules": [
                    {
                      "id": "E712",
                      "shortDescription": {"text": "Avoid equality comparisons to True"}
                    }
                  ]
                }
              },
              "results": [
                {
                  "ruleId": "E712",
                  "level": "warning",
                  "message": {"text": "Use direct truthiness instead of == True."},
                  "locations": [
                    {
                      "physicalLocation": {
                        "artifactLocation": {"uri": "src/missing.py"},
                        "region": {"startLine": 1}
                      }
                    }
                  ]
                }
              ]
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    config.sonarqube.mock_issues_path = fixture
    config.sarif.artifacts = [
        SarifArtifactConfig(
            path=repo_root / "artifacts" / "ruff.sarif",
            source_id="ruff-sarif",
        )
    ]

    collection = IssueIntakeService(
        repo_root=repo_root,
        config=config,
    ).collect_dashboard_sync_issues(dry_run=True, run_id="run-1")

    assert len(collection.finding_collection.findings) == 1
    assert collection.finding_collection.findings[0].source_id == "sonarqube"
    assert collection.finding_collection.metadata.managed_source_ids == ["sonarqube"]


def test_sync_uses_source_metadata_for_dashboard_fields() -> None:
    dashboard_service = FakeDashboardService()
    service = FindingDashboardSyncService(dashboard_service)

    finding = NormalizedFinding.model_validate(
        sonar_issue_to_normalized_finding(build_issue()).model_dump(mode="python")
    )

    service.sync(project_id="123", findings=[finding])

    item = dashboard_service.items[0]
    assert item.source_reference == "AX123"
    assert item.rule == "python:S1125"
    assert item.issue_type == "CODE_SMELL"
    assert item.component == "sample-project:src/service.py"
    assert item.project == "sample-project"


def test_sync_preserves_existing_status_for_current_sonar_items() -> None:
    dashboard_service = FakeDashboardService(
        DashboardDocument(
            issue_id=11,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Work Queue",
            sections=[
                DashboardSection(
                    key="merge_requests_opened",
                    title="Merge Requests Opened",
                    items=[
                        DashboardItem(
                            id="sonar:AX123",
                            source="sonarqube",
                            type="code_smell_fix",
                            status="mr_opened",
                            title="python:S1125 in src/service.py",
                            summary="Replace boolean equality with direct truthiness.",
                            priority="low",
                            source_reference="AX123",
                            file="src/service.py",
                            line=42,
                            rule="python:S1125",
                            severity="LOW",
                        )
                    ],
                )
            ],
        )
    )
    service = FindingDashboardSyncService(dashboard_service)

    service.sync(
        project_id="123",
        findings=[sonar_issue_to_normalized_finding(build_issue())],
    )

    assert dashboard_service.items[0].status == "mr_opened"


def test_sync_marks_missing_active_sonar_items_done() -> None:
    dashboard_service = FakeDashboardService(
        DashboardDocument(
            issue_id=11,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Work Queue",
            sections=[
                DashboardSection(
                    key="open_candidates",
                    title="Open Candidates",
                    items=[
                        DashboardItem(
                            id="sonar:STALE",
                            source="sonarqube",
                            type="code_smell_fix",
                            status="open",
                            title="python:S1125 in src/stale.py",
                            summary="Old issue.",
                            priority="low",
                            source_reference="STALE",
                            file="src/stale.py",
                            line=10,
                            rule="python:S1125",
                            severity="LOW",
                        )
                    ],
                )
            ],
        )
    )
    service = FindingDashboardSyncService(dashboard_service)

    service.sync(
        project_id="123",
        findings=[],
        managed_source_ids={"sonarqube"},
    )

    assert dashboard_service.items[0].id == "sonar:STALE"
    assert dashboard_service.items[0].status == "done"
    assert dashboard_service.items[0].upstream_active is False


def test_sync_preserves_missing_sonar_items_once_remediation_has_started() -> None:
    dashboard_service = FakeDashboardService(
        DashboardDocument(
            issue_id=11,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Work Queue",
            sections=[
                DashboardSection(
                    key="in_progress",
                    title="In Progress",
                    items=[
                        DashboardItem(
                            id="sonar:INPROGRESS",
                            source="sonarqube",
                            type="code_smell_fix",
                            status="in_progress",
                            title="python:S1125 in src/in_progress.py",
                            summary="Still being remediated.",
                            priority="low",
                            source_reference="INPROGRESS",
                            file="src/in_progress.py",
                            line=10,
                            rule="python:S1125",
                            severity="LOW",
                            branch_name="zeroone-ops/inprogress",
                            last_run_id="run-1",
                        )
                    ],
                ),
                DashboardSection(
                    key="merge_requests_opened",
                    title="Merge Requests Opened",
                    items=[
                        DashboardItem(
                            id="sonar:MROPENED",
                            source="sonarqube",
                            type="code_smell_fix",
                            status="mr_opened",
                            title="python:S1125 in src/mr_opened.py",
                            summary="Awaiting merge.",
                            priority="low",
                            source_reference="MROPENED",
                            file="src/mr_opened.py",
                            line=10,
                            rule="python:S1125",
                            severity="LOW",
                            branch_name="zeroone-ops/mr-opened",
                            last_run_id="run-2",
                            commit_sha="abc123",
                            merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/9",
                        )
                    ],
                ),
            ],
        )
    )
    service = FindingDashboardSyncService(dashboard_service)

    service.sync(
        project_id="123",
        findings=[],
        managed_source_ids={"sonarqube"},
    )

    items_by_id = {item.id: item for item in dashboard_service.items}
    assert items_by_id["sonar:INPROGRESS"].status == "in_progress"
    assert items_by_id["sonar:INPROGRESS"].last_run_id == "run-1"
    assert items_by_id["sonar:INPROGRESS"].upstream_active is False
    assert items_by_id["sonar:MROPENED"].status == "mr_opened"
    assert items_by_id["sonar:MROPENED"].merge_request_url is not None
    assert items_by_id["sonar:MROPENED"].upstream_active is False


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
