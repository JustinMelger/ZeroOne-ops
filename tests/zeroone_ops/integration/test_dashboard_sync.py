from pathlib import Path

from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.runner import sync_dashboard_sonar, sync_findings


def _unset_sonarqube_environment(monkeypatch) -> None:
    """Keep SARIF-only integration tests independent of local credentials."""
    for name in ("SONARQUBE_URL", "SONARQUBE_TOKEN", "SONARQUBE_PROJECT_KEY"):
        monkeypatch.delenv(name, raising=False)


def _search_open_issues_one(self) -> list[SonarIssue]:
    del self
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


def _search_open_issues_two(self) -> list[SonarIssue]:
    del self
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
        ),
        SonarIssue(
            key="AX124",
            rule="python:S1125",
            severity="LOW",
            type="CODE_SMELL",
            status="OPEN",
            message="Another eligible issue.",
            component="sample-project:src/service.py",
            project="sample-project",
            file_path="src/service.py",
            line=50,
        ),
    ]


def _search_open_issues_none(self) -> list[SonarIssue]:
    del self
    return []


def _find_no_open_merge_request(
    self,
    project_id: str,
    source_branch: str,
    target_branch: str,
) -> None:
    del self, project_id, source_branch, target_branch
    return None


def _sync_result(self, project_id: str, findings, managed_source_ids=None):
    del self, project_id
    return type(
        "SyncResult",
        (),
        {
            "synced_count": len(findings),
            "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
            "managed_source_ids": managed_source_ids,
        },
    )()


def test_sync_dashboard_sonar_dry_run_reports_eligible_issue_count(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main",
            "bootstrap_severities": ["LOW"]
          },
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "zeroone_ops.providers.sonar_client.SonarClient.search_open_issues",
        _search_open_issues_one,
    )

    summary = sync_dashboard_sonar(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run found 1 findings for dashboard sync." in summary.message


def test_sync_dashboard_sonar_ci_mode_publishes_dashboard_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "remediation": {
            "target_branch": "main",
            "bootstrap_severities": ["LOW"]
          },
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "zeroone_ops.providers.sonar_client.SonarClient.search_open_issues",
        _search_open_issues_two,
    )
    monkeypatch.setattr(
        "zeroone_ops.providers.gitlab_client.GitLabClient.find_open_merge_request",
        _find_no_open_merge_request,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.intake.finding_dashboard_sync_service.FindingDashboardSyncService.sync",
        _sync_result,
    )

    summary = sync_dashboard_sonar(dry_run=False)

    assert summary.status.value == "synced"
    assert "Synced 2 findings to the dashboard." in summary.message
    assert "https://gitlab.example.com/group/project/-/issues/11" in summary.message


def test_sync_dashboard_sonar_reports_no_eligible_issues_in_ci_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "remediation": {
            "target_branch": "main",
            "bootstrap_severities": ["LOW"]
          },
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def _sync_empty(self, project_id: str, findings, managed_source_ids=None):
        del self, project_id
        captured["findings"] = findings
        captured["managed_source_ids"] = managed_source_ids
        return type(
            "SyncResult",
            (),
            {
                "synced_count": len(findings),
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.sonar_client.SonarClient.search_open_issues",
        _search_open_issues_none,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.intake.finding_dashboard_sync_service.FindingDashboardSyncService.sync",
        _sync_empty,
    )

    summary = sync_dashboard_sonar(dry_run=False)

    assert summary.status.value == "synced"
    assert "Synced 0 findings to the dashboard." in summary.message
    assert captured["findings"] == []
    assert captured["managed_source_ids"] == {"sonarqube"}


def test_sync_findings_dry_run_reports_sarif_finding_count_on_gitlab(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _unset_sonarqube_environment(monkeypatch)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "ruff.sarif").write_text(
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
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main",
            "bootstrap_severities": ["LOW"]
          },
          "sarif": {
            "artifacts": [{"path": "artifacts/ruff.sarif", "source_id": "ruff-sarif"}]
          },
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    summary = sync_findings(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run found 1 findings for dashboard sync." in summary.message


def test_sync_dashboard_sonar_ci_mode_publishes_sarif_dashboard_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _unset_sonarqube_environment(monkeypatch)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "ruff.sarif").write_text(
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
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "remediation": {
            "target_branch": "main",
            "bootstrap_severities": ["LOW"]
          },
          "sarif": {
            "artifacts": [{"path": "artifacts/ruff.sarif", "source_id": "ruff-sarif"}]
          },
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.intake.finding_dashboard_sync_service.FindingDashboardSyncService.sync",
        _sync_result,
    )

    summary = sync_dashboard_sonar(dry_run=False)

    assert summary.status.value == "synced"
    assert "Synced 1 findings to the dashboard." in summary.message
    assert "https://gitlab.example.com/group/project/-/issues/11" in summary.message
