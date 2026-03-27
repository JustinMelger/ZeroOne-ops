from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import AppState, IssueState, RepositoryState
from ai_sonar_bot.services.issue_selector import IssueSelector


def build_config() -> AppConfig:
    return AppConfig(
        base_branch="main",
        supported_severities=["MAJOR"],
        supported_issue_types=["BUG"],
        validation_commands=[],
        analysis=AnalysisConfig(),
        approval=ApprovalConfig(),
        gitlab=GitLabConfig(target_branch="main"),
    )


def test_select_skips_issue_with_existing_merge_request() -> None:
    config = build_config()
    selector = IssueSelector(config)
    issues = [
        SonarIssue(
            key="A",
            rule="python:S123",
            severity="MAJOR",
            type="BUG",
            status="OPEN",
            message="Issue A",
            component="component",
            project="project",
            file_path="src/a.py",
        ),
        SonarIssue(
            key="B",
            rule="python:S124",
            severity="MAJOR",
            type="BUG",
            status="OPEN",
            message="Issue B",
            component="component",
            project="project",
            file_path="src/b.py",
        ),
    ]
    state = AppState(
        repository=RepositoryState(base_branch="main"),
        issues={"A": IssueState(status="mr_created", last_run_id="run-1")},
    )

    selected = selector.select(issues, state)

    assert selected is not None
    assert selected.key == "B"
