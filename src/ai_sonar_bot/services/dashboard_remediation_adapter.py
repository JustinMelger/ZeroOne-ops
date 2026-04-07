"""Adapters for reusing the current Sonar remediation engine."""

from __future__ import annotations

from ai_sonar_bot.models.remediation import RemediationWorkItem
from ai_sonar_bot.models.sonar import SonarIssue


def remediation_work_item_to_sonar_issue(work_item: RemediationWorkItem) -> SonarIssue:
    """Adapt one remediation work item into the current Sonar issue shape."""
    return SonarIssue(
        key=work_item.source_ref,
        rule=work_item.rule_id or "unknown",
        severity=work_item.severity or "UNKNOWN",
        type="CODE_SMELL",
        status="OPEN",
        message=work_item.message,
        component=work_item.file_path,
        project="dashboard-remediation",
        file_path=work_item.file_path,
        line=work_item.line,
    )
