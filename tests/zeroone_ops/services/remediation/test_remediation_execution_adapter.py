from zeroone_ops.models.finding import RemediationContext
from zeroone_ops.models.sonar import SonarIssue
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.remediation.remediation_execution_adapter import (
    control_plane_work_item_to_execution_target,
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
    assert work_item.issue_type == "CODE_SMELL"
    assert work_item.component == "sample-project:src/service.py"
    assert work_item.project == "sample-project"
    assert work_item.source_payload["issue_type"] == "CODE_SMELL"


def test_sonar_issue_to_execution_target_reuses_work_item_normalization() -> None:
    target = sonar_issue_to_execution_target(build_issue())

    assert target.item_id == "sonar:AX123"
    assert target.source_ref == "AX123"
    assert target.rule_id == "python:S1125"
    assert target.issue_type == "CODE_SMELL"
    assert target.component == "sample-project:src/service.py"
    assert target.project == "sample-project"


def test_work_item_target_adapter_preserves_shared_fields() -> None:
    work_item = sonar_issue_to_work_item(build_issue())
    target = remediation_work_item_to_execution_target(work_item)

    assert target.item_id == "sonar:AX123"
    assert target.source_type == "sonarqube"
    assert target.file_path == "src/service.py"
    assert target.issue_type == "CODE_SMELL"
    assert target.component == "sample-project:src/service.py"
    assert target.project == "sample-project"


def test_control_plane_work_item_adapter_uses_authoritative_identity() -> None:
    target = control_plane_work_item_to_execution_target(
        WorkItemState(
            work_item_id="work-1",
            kind="remediation",
            status="in_progress",
            source=WorkItemSourceRef(source="ruff", source_item_key="ruff:E712:service"),
            summary="Avoid equality comparisons to True",
            detail="Use direct truthiness instead of == True.",
            severity="medium",
            file_path="src/service.py",
            line=12,
            remediation_context=RemediationContext(
                category="static_analysis_fix",
                diagnostic_code="E712",
                validation_commands=["uv run ruff check src/service.py"],
                expected_change="Use direct truthiness.",
                constraints="Keep the expression side-effect free.",
                acceptance_criteria=["The E712 finding is resolved."],
            ),
        )
    )

    assert target.item_id == "work-1"
    assert target.source_type == "ruff"
    assert target.source_ref == "ruff:E712:service"
    assert target.status == "in_progress"
    assert target.message == "Use direct truthiness instead of == True."
    assert target.remediation_category == "static_analysis_fix"
    assert target.rule_id == "E712"
    assert target.validation_commands == ["uv run ruff check src/service.py"]
    assert target.expected_change == "Use direct truthiness."
    assert target.constraints == "Keep the expression side-effect free."
    assert target.acceptance_criteria == ["The E712 finding is resolved."]
