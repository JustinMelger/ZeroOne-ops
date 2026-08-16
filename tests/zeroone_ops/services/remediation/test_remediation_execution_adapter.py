from zeroone_ops.models.finding import RemediationContext
from zeroone_ops.models.remediation import RemediationWorkItem
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.remediation.remediation_execution_adapter import (
    control_plane_work_item_to_execution_target,
    remediation_work_item_to_execution_target,
)


def test_work_item_target_adapter_preserves_shared_fields() -> None:
    work_item = RemediationWorkItem(
        dashboard_item_id="ruff:E712:service",
        source_type="ruff-sarif",
        source_ref="ruff:E712:service",
        title="Avoid equality comparisons to True",
        status="approved",
        message="Replace boolean equality with direct truthiness.",
        file_path="src/service.py",
        line=42,
        rule_id="E712",
        severity="low",
        issue_type="lint_fix",
        component="sample-project:src/service.py",
        project="sample-project",
    )
    target = remediation_work_item_to_execution_target(work_item)

    assert target.item_id == "ruff:E712:service"
    assert target.source_type == "ruff-sarif"
    assert target.file_path == "src/service.py"
    assert target.issue_type == "lint_fix"
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


def test_control_plane_work_item_adapter_keeps_the_authoritative_issue_url() -> None:
    target = control_plane_work_item_to_execution_target(
        WorkItemState(
            work_item_id="work-1",
            kind="remediation",
            status="approved",
            source=WorkItemSourceRef(source="ruff", source_item_key="ruff:E712:service"),
            summary="Avoid equality comparisons to True",
            detail=None,
            severity="medium",
            file_path="src/service.py",
        ),
        work_item_url="https://github.example.com/octo-org/octo-repo/issues/11",
    )

    assert target.work_item_url == "https://github.example.com/octo-org/octo-repo/issues/11"
