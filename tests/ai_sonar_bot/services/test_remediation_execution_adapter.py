from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.services.remediation.remediation_execution_adapter import (
    remediation_work_item_to_execution_target,
    sonar_issue_to_execution_target,
    sonar_issue_to_work_item,
)


def build_issue() -> SonarIssue:
    return SonarIssue(
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


def test_sonar_issue_to_work_item_normalizes_direct_sonar_input() -> None:
    work_item = sonar_issue_to_work_item(build_issue())

    assert work_item.dashboard_item_id == "sonar:AX123"
    assert work_item.source_type == "sonarqube"
    assert work_item.source_ref == "AX123"
    assert work_item.rule_id == "python:S1125"
    assert work_item.source_payload["issue_type"] == "CODE_SMELL"


def test_sonar_issue_to_execution_target_reuses_work_item_normalization() -> None:
    target = sonar_issue_to_execution_target(build_issue())

    assert target.item_id == "sonar:AX123"
    assert target.source_ref == "AX123"
    assert target.rule_id == "python:S1125"
    assert target.issue_type == "CODE_SMELL"


def test_work_item_target_adapter_preserves_shared_fields() -> None:
    work_item = sonar_issue_to_work_item(build_issue())
    target = remediation_work_item_to_execution_target(work_item)

    assert target.item_id == "sonar:AX123"
    assert target.source_type == "sonarqube"
    assert target.file_path == "src/service.py"
