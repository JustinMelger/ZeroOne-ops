from zeroone_ops.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.models.state import AppState, IssueState, RepositoryState
from zeroone_ops.services.intake.issue_selector import IssueSelector


def build_config() -> AppConfig:
    return AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            bootstrap_severities=["LOW"],
            analysis=AnalysisConfig(),
        ),
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
            impacts=[],
        ),
        SonarIssue(
            key="B",
            rule="python:S124",
            severity="MINOR",
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


def test_select_uses_maintainability_low_when_present() -> None:
    config = build_config()
    selector = IssueSelector(config)
    issues = [
        SonarIssue(
            key="LOW-1",
            rule="python:S1125",
            severity="UNKNOWN",
            type="BUG",
            status="OPEN",
            message="Issue",
            component="component",
            project="project",
            file_path="src/a.py",
            impacts=[
                {
                    "software_quality": "MAINTAINABILITY",
                    "severity": "LOW",
                }
            ],
        )
    ]
    state = AppState(repository=RepositoryState(base_branch="main"))

    selected = selector.select(issues, state)

    assert selected is not None
    assert selected.key == "LOW-1"


def test_select_skips_risky_rename_issue_and_moves_to_next() -> None:
    config = build_config()
    selector = IssueSelector(config)
    issues = [
        SonarIssue(
            key="RENAME-1",
            rule="python:S9999",
            severity="UNKNOWN",
            type="BUG",
            status="OPEN",
            message="Rename this variable to match the regular expression.",
            component="component",
            project="project",
            file_path="src/a.py",
            impacts=[
                {
                    "software_quality": "MAINTAINABILITY",
                    "severity": "LOW",
                }
            ],
        ),
        SonarIssue(
            key="LOW-2",
            rule="python:S1125",
            severity="UNKNOWN",
            type="BUG",
            status="OPEN",
            message="Boolean literals should not be used in comparisons.",
            component="component",
            project="project",
            file_path="src/b.py",
            impacts=[
                {
                    "software_quality": "MAINTAINABILITY",
                    "severity": "LOW",
                }
            ],
        ),
    ]
    state = AppState(repository=RepositoryState(base_branch="main"))

    selected = selector.select(issues, state)

    assert selected is not None
    assert selected.key == "LOW-2"
