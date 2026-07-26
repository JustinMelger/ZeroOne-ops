"""Dashboard remediation item normalization."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.models.remediation import (
    RemediationWorkItem,
    is_remediation_eligible_category,
)


@dataclass(frozen=True)
class DashboardItemNormalizationResult:
    """Capture the normalization outcome for one dashboard item."""

    work_item: RemediationWorkItem | None
    message: str = ""


class DashboardItemNormalizer:
    """Normalize dashboard items into provider-neutral remediation work items."""

    def normalize(self, item: DashboardItem) -> DashboardItemNormalizationResult:
        """Validate and normalize one dashboard item."""
        if item.status != "open":
            return DashboardItemNormalizationResult(
                work_item=None,
                message=f"Dashboard item {item.id} is not open.",
            )
        if not is_remediation_eligible_category(item.type):
            return DashboardItemNormalizationResult(
                work_item=None,
                message=f"Dashboard item {item.id} uses unsupported type {item.type}.",
            )
        if item.file is None:
            return DashboardItemNormalizationResult(
                work_item=None,
                message=f"Dashboard item {item.id} is missing a target file path.",
            )
        if not item.source_reference:
            return DashboardItemNormalizationResult(
                work_item=None,
                message=f"Dashboard item {item.id} is missing a source reference.",
            )
        return DashboardItemNormalizationResult(
            work_item=RemediationWorkItem(
                dashboard_item_id=item.id,
                source_type=item.source,
                source_ref=item.source_reference,
                title=item.title,
                status=item.status,
                message=item.summary,
                file_path=item.file,
                line=item.line,
                rule_id=item.rule,
                severity=item.automation_severity or item.severity,
                issue_type=item.issue_type,
                component=item.component,
                project=item.project,
                source_payload=item.model_dump(mode="python"),
                validation_commands=list(item.validation_commands),
                expected_change=item.expected_change,
                constraints=item.constraints,
                acceptance_criteria=list(item.acceptance_criteria),
            )
        )
