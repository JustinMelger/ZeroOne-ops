from pathlib import Path

from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.runner import run


def test_run_dry_run_creates_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.delenv("SONARQUBE_URL", raising=False)
    monkeypatch.delenv("SONARQUBE_TOKEN", raising=False)
    monkeypatch.delenv("SONARQUBE_PROJECT_KEY", raising=False)
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    summary = run(dry_run=True)

    assert summary.status.value == "no_issue"
    assert "SonarQube credentials not configured" in summary.message


def test_run_selects_issue_with_existing_local_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = None\n", encoding="utf-8")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def fake_search_open_issues(self) -> list[SonarIssue]:
        del self
        return [
            SonarIssue(
                key="AX12345",
                rule="python:S2259",
                severity="MAJOR",
                type="BUG",
                status="OPEN",
                message="Add a null check.",
                component="sample-project:src/service.py",
                project="sample-project",
                file_path="src/service.py",
                line=1,
            )
        ]

    monkeypatch.setattr(
        "ai_sonar_bot.providers.sonar_client.SonarClient.search_open_issues",
        fake_search_open_issues,
    )

    summary = run(dry_run=True)

    assert summary.status.value == "selected"
    assert "AX12345" in summary.message
    assert "src/service.py" in summary.message


def test_run_dry_run_uses_fixture_when_configured(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    fixture_dir = tmp_path / "fixtures" / "sonar"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "issues.json").write_text(
        """
        {
          "issues": [
            {
              "key": "FIXTURE-1",
              "rule": "python:S2259",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "Fixture issue",
              "component": "sample-project:src/service.py",
              "project": "sample-project",
              "line": 1
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "mock_sonar_issues_path": "fixtures/sonar/issues.json",
          "supported_severities": ["MAJOR"],
          "supported_issue_types": ["BUG"],
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    summary = run(dry_run=True)

    assert summary.status.value == "selected"
    assert "FIXTURE-1" in summary.message
