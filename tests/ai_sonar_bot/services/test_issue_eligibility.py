from ai_sonar_bot.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import AppState, IssueState, RepositoryState
from ai_sonar_bot.services.intake.issue_eligibility import IssueEligibilityPolicy


def build_config() -> AppConfig:
    return AppConfig(
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            supported_severities=["LOW"],
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(target_branch="main"),
    )


def test_policy_rejects_rename_style_issue() -> None:
    policy = IssueEligibilityPolicy(build_config())
    issue = SonarIssue(
        key="RENAME-1",
        rule="python:S9999",
        severity="UNKNOWN",
        type="BUG",
        status="OPEN",
        message="Rename this variable to match the regular expression.",
        component="component",
        project="project",
        file_path="src/a.py",
        impacts=[{"software_quality": "MAINTAINABILITY", "severity": "LOW"}],
    )

    assert (
        policy.skip_reason(issue, AppState(repository=RepositoryState(base_branch="main")))
        == "risky_rename"
    )


def test_policy_rejects_existing_merge_request_issue() -> None:
    policy = IssueEligibilityPolicy(build_config())
    issue = SonarIssue(
        key="LOW-1",
        rule="python:S1125",
        severity="UNKNOWN",
        type="BUG",
        status="OPEN",
        message="Boolean literals should not be used in comparisons.",
        component="component",
        project="project",
        file_path="src/a.py",
        impacts=[{"software_quality": "MAINTAINABILITY", "severity": "LOW"}],
    )
    state = AppState(
        repository=RepositoryState(base_branch="main"),
        issues={"LOW-1": IssueState(status="mr_created", last_run_id="run-1")},
    )

    assert policy.skip_reason(issue, state) == "existing_merge_request"


def test_policy_rejects_unsupported_issue_type() -> None:
    policy = IssueEligibilityPolicy(build_config())
    issue = SonarIssue(
        key="LOW-2",
        rule="python:S1481",
        severity="UNKNOWN",
        type="SECURITY_HOTSPOT",
        status="OPEN",
        message="Remove this unused local variable.",
        component="component",
        project="project",
        file_path="src/a.py",
        impacts=[{"software_quality": "MAINTAINABILITY", "severity": "LOW"}],
    )

    assert (
        policy.skip_reason(issue, AppState(repository=RepositoryState(base_branch="main")))
        == "unsupported_type"
    )
