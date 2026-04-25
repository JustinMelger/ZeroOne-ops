from ai_sonar_bot.models.analysis import ValidationResult
from ai_sonar_bot.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    RemediationConfig,
)
from ai_sonar_bot.models.remediation import RemediationExecutionTarget
from ai_sonar_bot.services.remediation.publish_service import PublishService


def build_config() -> AppConfig:
    return AppConfig(
        execution_mode="ci",
        base_branch="main",
        validation_commands=[],
        approval=ApprovalConfig(),
        remediation=RemediationConfig(
            supported_severities=["MAJOR"],
            analysis=AnalysisConfig(),
        ),
        gitlab=GitLabConfig(target_branch="main", labels=["ai-sonar-bot"]),
    )


def build_issue() -> RemediationExecutionTarget:
    return RemediationExecutionTarget(
        item_id="FIXTURE-1",
        source_type="sonarqube",
        source_ref="FIXTURE-1",
        title="python:S2259 in src/service.py",
        status="OPEN",
        message="Fixture issue",
        file_path="src/service.py",
        line=1,
        rule_id="python:S2259",
        severity="MAJOR",
        issue_type="BUG",
        component="sample-project:src/service.py",
        project="sample-project",
    )


class StubBranchManager:
    def push_current_branch(self, *, remote_name: str = "origin") -> str:
        del remote_name
        return "zeroone-ops/fix"


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
            "## Remediation Target",
            "- Source: `SonarQube`",
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


def test_publish_service_uses_generic_profile_for_unknown_source() -> None:
    service = PublishService(config=build_config(), branch_manager=StubBranchManager())  # type: ignore[arg-type]

    description = service.build_mr_description(
        selected_issue=RemediationExecutionTarget(
            item_id="pipeline:1",
            source_type="pipeline_failure",
            source_ref="job-1",
            title="pytest failed in src/service.py",
            status="open",
            message="Test suite is failing.",
            file_path="src/service.py",
        ),
        validation_result=ValidationResult(
            passed=True,
            results=[],
            summary="All validation commands passed.",
        ),
        change_summary="summary",
    )

    assert "## Remediation Target" in description
    assert "- Source: `Remediation`" in description
    assert "- Item reference: `job-1`" in description
