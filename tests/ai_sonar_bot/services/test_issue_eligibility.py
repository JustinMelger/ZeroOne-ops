from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import AppState, IssueState, RepositoryState
from ai_sonar_bot.services.issue_eligibility import IssueEligibilityPolicy


def build_config(*, supported_rules: list[str] | None = None) -> AppConfig:
    return AppConfig(
        base_branch="main",
        supported_severities=["LOW"],
        supported_issue_types=["BUG"],
        supported_rules=supported_rules or [],
        validation_commands=[],
        analysis=AnalysisConfig(),
        approval=ApprovalConfig(),
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


def test_policy_rejects_rule_outside_allowlist() -> None:
    policy = IssueEligibilityPolicy(build_config(supported_rules=["python:S1125"]))
    issue = SonarIssue(
        key="LOW-2",
        rule="python:S1481",
        severity="UNKNOWN",
        type="BUG",
        status="OPEN",
        message="Remove this unused local variable.",
        component="component",
        project="project",
        file_path="src/a.py",
        impacts=[{"software_quality": "MAINTAINABILITY", "severity": "LOW"}],
    )

    assert (
        policy.skip_reason(issue, AppState(repository=RepositoryState(base_branch="main")))
        == "unsupported_rule"
    )
