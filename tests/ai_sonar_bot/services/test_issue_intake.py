from pathlib import Path

from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.state import AppState, RepositoryState
from ai_sonar_bot.services.issue_intake import IssueIntakeService


def build_config(*, mock_sonar_issues_path: Path | None = None) -> AppConfig:
    return AppConfig(
        base_branch="main",
        supported_severities=["MAJOR"],
        supported_issue_types=["BUG"],
        validation_commands=[],
        analysis=AnalysisConfig(),
        approval=ApprovalConfig(),
        gitlab=GitLabConfig(target_branch="main"),
        mock_sonar_issues_path=mock_sonar_issues_path,
    )


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


def test_select_issue_uses_existing_fixture_file_only(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    fixture_path = tmp_path / "issues.json"
    fixture_path.write_text(
        """
        {
          "issues": [
            {
              "key": "MISSING",
              "rule": "python:S2259",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "Missing file",
              "component": "sample-project:src/missing.py",
              "project": "sample-project",
              "line": 1
            },
            {
              "key": "EXISTING",
              "rule": "python:S2259",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "Existing file",
              "component": "sample-project:src/service.py",
              "project": "sample-project",
              "line": 1
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    result = IssueIntakeService(
        repo_root=tmp_path,
        config=build_config(mock_sonar_issues_path=fixture_path),
    ).select_issue(state=build_state(), dry_run=True, run_id="run-1")

    assert result.issue_count == 2
    assert result.selected_issue is not None
    assert result.selected_issue.key == "EXISTING"
    assert result.message == ""


def test_select_issue_returns_message_when_no_fixture_issue_matches(tmp_path: Path) -> None:
    fixture_path = tmp_path / "issues.json"
    fixture_path.write_text(
        """
        {
          "issues": [
            {
              "key": "ONLY",
              "rule": "python:S2259",
              "severity": "MINOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "Not supported",
              "component": "sample-project:src/service.py",
              "project": "sample-project",
              "line": 1
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )

    result = IssueIntakeService(
        repo_root=tmp_path,
        config=build_config(mock_sonar_issues_path=fixture_path),
    ).select_issue(state=build_state(), dry_run=True, run_id="run-1")

    assert result.selected_issue is None
    assert "No eligible SonarQube issue found in fixture" in result.message
