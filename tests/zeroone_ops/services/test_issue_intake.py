import logging
from pathlib import Path

from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
    SonarQubeConfig,
)
from zeroone_ops.models.gitlab import MergeRequestInfo
from zeroone_ops.models.state import AppState, IssueState, RepositoryState
from zeroone_ops.services.intake.issue_intake import IssueIntakeService


def build_config(
    *,
    mock_sonar_issues_path: Path | None = None,
    execution_mode: str = "local",
) -> AppConfig:
    return AppConfig(
        execution_mode=execution_mode,
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            supported_severities=["MAJOR"],
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(target_branch="main"),
        sonarqube=SonarQubeConfig(mock_issues_path=mock_sonar_issues_path),
    )


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


class FakeMergeRequestService:
    def __init__(self, branches_with_open_mr: set[str]) -> None:
        self.branches_with_open_mr = branches_with_open_mr

    def find_open(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
    ) -> MergeRequestInfo | None:
        del project_id, target_branch
        if source_branch not in self.branches_with_open_mr:
            return None
        return MergeRequestInfo(
            iid=1,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/1",
            title="fix: existing issue",
        )


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
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
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
    assert "with unsupported severity" in result.message


def test_select_issue_skips_state_tracked_in_progress_issue_and_moves_to_next(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("value = 2\n", encoding="utf-8")
    fixture_path = tmp_path / "issues.json"
    fixture_path.write_text(
        """
        {
          "issues": [
            {
              "key": "FIRST",
              "rule": "python:S2259",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "First issue",
              "component": "sample-project:src/service.py",
              "project": "sample-project",
              "line": 1
            },
            {
              "key": "SECOND",
              "rule": "python:S2259",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "Second issue",
              "component": "sample-project:src/other.py",
              "project": "sample-project",
              "line": 1
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    state = AppState(
        repository=RepositoryState(base_branch="main"),
        issues={
            "FIRST": IssueState(
                status="mr_created",
                last_run_id="run-1",
            )
        },
    )

    result = IssueIntakeService(
        repo_root=tmp_path,
        config=build_config(mock_sonar_issues_path=fixture_path),
    ).select_issue(state=state, dry_run=True, run_id="run-1")

    assert result.selected_issue is not None
    assert result.selected_issue.key == "SECOND"


def test_select_issue_skips_issue_with_existing_open_merge_request_in_ci(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "src" / "other.py").write_text("value = 2\n", encoding="utf-8")
    fixture_path = tmp_path / "issues.json"
    fixture_path.write_text(
        """
        {
          "issues": [
            {
              "key": "FIRST",
              "rule": "python:S2259",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "First issue",
              "component": "sample-project:src/service.py",
              "project": "sample-project",
              "line": 1
            },
            {
              "key": "SECOND",
              "rule": "python:S2259",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "Second issue",
              "component": "sample-project:src/other.py",
              "project": "sample-project",
              "line": 1
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    config = build_config(
        mock_sonar_issues_path=fixture_path,
        execution_mode="ci",
    )
    caplog.set_level(logging.INFO)

    result = IssueIntakeService(
        repo_root=tmp_path,
        config=config,
        merge_request_service=FakeMergeRequestService({"zeroone-ops/first/service"}),
    ).select_issue(state=build_state(), dry_run=True, run_id="run-1")

    assert result.selected_issue is not None
    assert result.selected_issue.key == "SECOND"
    assert "skipped issue during intake" in caplog.text


def test_select_issue_reports_skip_reasons_when_all_candidates_are_in_progress(
    tmp_path: Path,
    caplog,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    fixture_path = tmp_path / "issues.json"
    fixture_path.write_text(
        """
        {
          "issues": [
            {
              "key": "FIRST",
              "rule": "python:S2259",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "First issue",
              "component": "sample-project:src/service.py",
              "project": "sample-project",
              "line": 1
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    state = AppState(
        repository=RepositoryState(base_branch="main"),
        issues={"FIRST": IssueState(status="mr_created", last_run_id="run-1")},
    )
    caplog.set_level(logging.INFO)

    result = IssueIntakeService(
        repo_root=tmp_path,
        config=build_config(mock_sonar_issues_path=fixture_path),
    ).select_issue(state=state, dry_run=True, run_id="run-1")

    assert result.selected_issue is None
    assert "already in progress locally" in result.message
    assert "skipped issue during intake" in caplog.text


def test_select_issue_reports_rename_skip_reason_when_all_candidates_are_filtered(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    fixture_path = tmp_path / "issues.json"
    fixture_path.write_text(
        """
        {
          "issues": [
            {
              "key": "RENAME-1",
              "rule": "python:S9999",
              "severity": "MAJOR",
              "type": "BUG",
              "status": "OPEN",
              "message": "Rename this variable to match the regular expression.",
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
    assert "rename-style issues" in result.message
