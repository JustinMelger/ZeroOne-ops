"""Adapters into the shared remediation execution contract."""

from __future__ import annotations

from zeroone_ops.models.remediation import RemediationExecutionTarget, RemediationWorkItem
from zeroone_ops.models.work_item import WorkItemState


def remediation_work_item_to_execution_target(
    work_item: RemediationWorkItem,
) -> RemediationExecutionTarget:
    """Adapt one remediation work item into the shared execution target shape."""
    return RemediationExecutionTarget(
        item_id=work_item.dashboard_item_id,
        source_type=work_item.source_type,
        source_ref=work_item.source_ref,
        title=work_item.title,
        status=work_item.status,
        message=work_item.message,
        file_path=work_item.file_path,
        line=work_item.line,
        rule_id=work_item.rule_id,
        severity=work_item.severity,
        remediation_category=work_item.remediation_category,
        issue_type=work_item.issue_type,
        component=work_item.component,
        project=work_item.project,
        source_payload=work_item.source_payload,
        validation_commands=work_item.validation_commands,
        expected_change=work_item.expected_change,
        constraints=work_item.constraints,
        acceptance_criteria=work_item.acceptance_criteria,
    )


def control_plane_work_item_to_execution_target(
    work_item: WorkItemState,
    *,
    work_item_url: str | None = None,
) -> RemediationExecutionTarget:
    """Adapt one authoritative work item into the shared execution target shape."""
    if work_item.file_path is None:
        raise ValueError("Work item is missing a target file path.")
    return RemediationExecutionTarget(
        item_id=work_item.work_item_id,
        source_type=work_item.source.source,
        source_ref=work_item.source.source_item_key,
        work_item_url=work_item_url,
        title=work_item.summary,
        status=work_item.status,
        message=work_item.detail or work_item.summary,
        file_path=work_item.file_path,
        line=work_item.line,
        rule_id=work_item.remediation_context.diagnostic_code,
        severity=work_item.severity,
        remediation_category=work_item.remediation_context.category,
        validation_commands=work_item.remediation_context.validation_commands,
        expected_change=work_item.remediation_context.expected_change,
        constraints=work_item.remediation_context.constraints,
        acceptance_criteria=work_item.remediation_context.acceptance_criteria,
    )
