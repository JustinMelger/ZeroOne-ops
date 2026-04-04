from ai_sonar_bot.models.analysis import ValidationResult
from ai_sonar_bot.models.config import AnalysisConfig, AppConfig, ApprovalConfig, GitLabConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.services.publish_service import PublishService


def build_config() -> AppConfig:
    return AppConfig(
        execution_mode="ci",
        base_branch="main",
        supported_severities=["MAJOR"],
        supported_issue_types=["BUG"],
        validation_commands=[],
        analysis=AnalysisConfig(),
        approval=ApprovalConfig(),
        gitlab=GitLabConfig(target_branch="main", labels=["ai-sonar-bot"]),
    )


def build_issue() -> SonarIssue:
    return SonarIssue(
        key="FIXTURE-1",
        rule="python:S2259",
        severity="MAJOR",
        type="BUG",
        status="OPEN",
        message="Fixture issue",
        component="sample-project:src/service.py",
        project="sample-project",
        file_path="src/service.py",
        line=1,
    )


class StubBranchManager:
    def push_current_branch(self, *, remote_name: str = "origin") -> str:
        del remote_name
        return "ai-sonar/fix"


def test_publish_service_builds_deterministic_description() -> None:
    service = PublishService(config=build_config(), branch_manager=StubBranchManager())  # type: ignore[arg-type]

    description = service.build_mr_description(
        selected_issue=build_issue(),
        validation_result=ValidationResult(
            passed=True,
            results=[],
            summary="All validation commands passed.",
        ),
        change_summary="summary",
    )

    assert description == "\n".join(
        [
            "## Summary",
            "summary",
            "",
            "## SonarQube",
            "- Issue key: `FIXTURE-1`",
            "- Rule: `python:S2259`",
            "- Severity: `MAJOR`",
            "- Type: `BUG`",
            "- File: `src/service.py`",
            "- Line: `1`",
            "- Message: Fixture issue",
            "",
            "## Validation",
            "- All validation commands passed.",
            "",
            "## Notes",
            "- Diff was rendered by the bot from a structured edit proposal.",
        ]
    )
