"""Adapters into the shared remediation execution contract."""

from __future__ import annotations

from zeroone_ops.models.remediation import RemediationExecutionTarget, RemediationWorkItem
from zeroone_ops.models.sonar import SonarIssue
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
) -> RemediationExecutionTarget:
    """Adapt one authoritative work item into the shared execution target shape."""
    if work_item.file_path is None:
        raise ValueError("Work item is missing a target file path.")
    return RemediationExecutionTarget(
        item_id=work_item.work_item_id,
        source_type=work_item.source.source,
        source_ref=work_item.source.source_item_key,
        title=work_item.summary,
        status=work_item.status,
        message=work_item.detail or work_item.summary,
        file_path=work_item.file_path,
        line=work_item.line,
        severity=work_item.severity,
    )


def sonar_issue_to_work_item(issue: SonarIssue) -> RemediationWorkItem:
    """Adapt one SonarQube issue into the shared remediation work-item shape."""
    return RemediationWorkItem(
        dashboard_item_id=f"sonar:{issue.key}",
        source_type="sonarqube",
        source_ref=issue.key,
        title=f"{issue.rule} in {issue.file_path}",
        status=issue.status,
        message=issue.message,
        file_path=issue.file_path,
        line=issue.line,
        rule_id=issue.rule,
        severity=issue.severity,
        issue_type=issue.type,
        component=issue.component,
        project=issue.project,
        source_payload={
            "issue_type": issue.type,
            "component": issue.component,
            "project": issue.project,
            "effort": issue.effort,
            "tags": issue.tags,
            "impacts": [impact.model_dump(mode="json") for impact in issue.impacts],
            "creation_date": (
                issue.creation_date.isoformat() if issue.creation_date is not None else None
            ),
        },
    )


def sonar_issue_to_execution_target(issue: SonarIssue) -> RemediationExecutionTarget:
    """Adapt one SonarQube issue into the shared execution target shape."""
    work_item = sonar_issue_to_work_item(issue)
    return remediation_work_item_to_execution_target(work_item)
