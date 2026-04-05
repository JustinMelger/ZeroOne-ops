from pathlib import Path

from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.runner import sync_dashboard_sonar


def test_sync_dashboard_sonar_dry_run_reports_eligible_issue_count(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_CONFIG", str(tmp_path / ".ai-sonar-bot.json"))
    monkeypatch.setenv("SONARQUBE_URL", "https://sonarqube.example.com")
    monkeypatch.setenv("SONARQUBE_TOKEN", "token")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "sample-project")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "supported_severities": ["LOW"],
          "supported_issue_types": ["CODE_SMELL"],
          "supported_rules": ["python:S1125"],
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "ai_sonar_bot.providers.sonar_client.SonarClient.search_open_issues",
        lambda self: [
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
        ],
    )

    summary = sync_dashboard_sonar(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run found 1 eligible SonarQube issues for dashboard sync." in summary.message
