import json
import logging
from pathlib import Path

from pytest import LogCaptureFixture, MonkeyPatch

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
from zeroone_ops.models.finding import (
    FindingCollectionMetadata,
    FindingCollectionResult,
)
from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.providers.sonar_client import SonarClientError
from zeroone_ops.services.intake.issue_intake import IssueIntakeService


def test_unavailable_sonar_discards_source_and_continues_sarif(
    tmp_path: Path, monkeypatch: MonkeyPatch, caplog: LogCaptureFixture
) -> None:
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "secret")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")

    def fail_collection(self: object) -> list[SonarIssue]:
        raise SonarClientError("secret response content")

    monkeypatch.setattr(
        "zeroone_ops.providers.sonar_client.SonarClient.search_open_issues", fail_collection
    )
    (tmp_path / "service.py").write_text("flag = True\n", encoding="utf-8")
    artifact = tmp_path / "ruff.sarif"
    artifact.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "tool": {"driver": {"name": "Ruff"}},
                        "results": [
                            {
                                "ruleId": "E712",
                                "level": "warning",
                                "message": {"text": "Simplify comparison."},
                                "locations": [
                                    {
                                        "physicalLocation": {
                                            "artifactLocation": {"uri": "service.py"},
                                            "region": {"startLine": 1},
                                        }
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    config = AppConfig(
        base_branch="main",
        gitlab=GitLabConfig(target_branch="main"),
        sarif=SarifConfig(artifacts=[SarifArtifactConfig(path=artifact, source_id="ruff-sarif")]),
    )
    collection = (
        IssueIntakeService(tmp_path, config)
        .collect_findings_for_sync(dry_run=False, run_id="failed-sonar")
        .finding_collection
    )

    assert len(collection.findings) == 1
    assert collection.findings[0].source_id == "ruff-sarif"
    assert collection.metadata.managed_source_ids == ["ruff-sarif"]
    assert collection.metadata.input_collections[0].source_id == "sonarqube"
    assert collection.metadata.input_collections[0].managed_source_ids == []
    assert collection.metadata.statistics["unavailable_sources"] == 1
    assert len(collection.metadata.warnings) == 1
    assert "SonarQube inventory unavailable" in caplog.text
    assert "secret" not in caplog.text


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
    ).collect_findings_for_sync(dry_run=True, run_id="run-1")

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
    ).collect_findings_for_sync(dry_run=True, run_id="run-1")

    metadata = collection.finding_collection.metadata
    assert metadata.managed_source_ids == []
    assert metadata.input_collections[0].source_id == "ruff-sarif"
    assert metadata.input_collections[0].artifact_reference == str(
        tmp_path / "artifacts" / "missing.sarif"
    )
    assert metadata.warnings == ["SARIF artifact for source 'ruff-sarif' was unavailable."]
    assert metadata.statistics == {"unavailable_artifacts": 1}
    assert "skipped unavailable SARIF artifact" in caplog.text


def test_intake_logs_normalized_finding_count_per_sarif_source(
    tmp_path: Path,
    caplog: LogCaptureFixture,
) -> None:
    artifact_path = tmp_path / "artifacts" / "ruff.sarif"
    mypy_artifact_path = tmp_path / "artifacts" / "mypy.sarif"
    artifact_path.parent.mkdir()
    artifact_path.write_text(
        """
        {
          "runs": [{
            "tool": {"driver": {"name": "Ruff", "rules": [{"id": "E712"}]}},
            "results": [{
              "ruleId": "E712",
              "level": "warning",
              "message": {"text": "Use direct truthiness."},
              "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": "src/service.py"},
                "region": {"startLine": 1}
              }}]
            }]
          }]
        }
        """.strip(),
        encoding="utf-8",
    )
    mypy_artifact_path.write_text(
        artifact_path.read_text(encoding="utf-8").replace('"Ruff"', '"mypy"'),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = flag == True\n", encoding="utf-8")
    config = AppConfig(
        base_branch="main",
        remediation=RemediationConfig(target_branch="main"),
        gitlab=GitLabConfig(target_branch="main"),
        sarif=SarifConfig(
            artifacts=[
                SarifArtifactConfig(path=artifact_path, source_id="ruff-sarif"),
                SarifArtifactConfig(path=mypy_artifact_path, source_id="mypy-sarif"),
            ]
        ),
    )
    caplog.set_level(logging.INFO, logger="zeroone_ops.services.intake.issue_intake")

    IssueIntakeService(repo_root=tmp_path, config=config).collect_findings_for_sync(
        dry_run=True,
        run_id="run-1",
    )

    assert "finding intake source=ruff-sarif normalized_findings=1 run_id=run-1" in caplog.text
    assert "finding intake source=mypy-sarif normalized_findings=1 run_id=run-1" in caplog.text


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
    ).collect_findings_for_sync(dry_run=True, run_id="run-1")

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
    ).collect_findings_for_sync(dry_run=True, run_id="run-1")

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
    ).collect_findings_for_sync(dry_run=True, run_id="run-1")

    assert len(collection.finding_collection.findings) == 1
    assert collection.finding_collection.findings[0].source_id == "sonarqube"
    assert collection.finding_collection.metadata.managed_source_ids == ["sonarqube"]


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
