"""SonarQube discovery mirroring to the dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.dashboard import DashboardDocument, DashboardItem
from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.services.dashboard.dashboard_service import DashboardService

_DISCOVERY_OWNED_SONAR_STATUSES = frozenset({"open"})


@dataclass(frozen=True)
class SonarDashboardSyncResult:
    """Capture the outcome of syncing Sonar issues to the dashboard."""

    synced_count: int
    dashboard_issue_url: str | None = None


class SonarDashboardSyncService:
    """Mirror eligible SonarQube issues to the dashboard."""

    def __init__(self, dashboard_service: DashboardService) -> None:
        """Initialize the sync service."""
        self.dashboard_service = dashboard_service

    def sync(
        self,
        *,
        project_id: str,
        findings: list[NormalizedFinding],
    ) -> SonarDashboardSyncResult:
        """Upsert eligible normalized SonarQube findings into the dashboard."""
        document = self.dashboard_service.load_or_create(project_id=project_id)
        items = self._build_reconciled_items(document=document, findings=findings)
        document = self.dashboard_service.upsert_items(project_id=project_id, items=items)
        return SonarDashboardSyncResult(
            synced_count=len(findings),
            dashboard_issue_url=document.issue_url,
        )

    def _build_reconciled_items(
        self,
        *,
        document: DashboardDocument,
        findings: list[NormalizedFinding],
    ) -> list[DashboardItem]:
        """Return current Sonar items plus stale-item reconciliation updates."""
        existing_items = document.items_by_id()
        current_issue_ids = {self._dashboard_item_id(finding) for finding in findings}
        items = [
            self._normalize_finding(
                finding,
                existing=existing_items.get(self._dashboard_item_id(finding)),
            )
            for finding in findings
        ]
        for item in existing_items.values():
            if item.source != "sonarqube" or item.id in current_issue_ids:
                continue
            if item.status in _DISCOVERY_OWNED_SONAR_STATUSES:
                items.append(item.model_copy(update={"status": "done", "upstream_active": False}))
                continue
            items.append(item.model_copy(update={"upstream_active": False}))
        return items

    def _normalize_finding(
        self,
        finding: NormalizedFinding,
        *,
        existing: DashboardItem | None = None,
    ) -> DashboardItem:
        """Normalize one SonarQube finding into a dashboard item."""
        source_metadata = finding.source_metadata
        attributes = {} if source_metadata is None else source_metadata.attributes
        source_reference = source_metadata.native_id if source_metadata is not None else None
        source_reference = source_reference or finding.finding_id
        diagnostic_code = finding.remediation_context.diagnostic_code
        source_severity = attributes.get("source_severity")
        component = attributes.get("component")
        project = attributes.get("project")
        issue_type = attributes.get("type")
        return DashboardItem(
            id=self._dashboard_item_id(finding),
            source="sonarqube",
            type=existing.type if existing is not None else "code_smell_fix",
            status=existing.status if existing is not None else "open",
            title=finding.title,
            summary=finding.summary,
            priority=_priority_from_severity(finding.severity),
            source_reference=source_reference,
            file=finding.repository_path,
            line=finding.line_start,
            rule=diagnostic_code,
            issue_type=issue_type if isinstance(issue_type, str) else None,
            component=component if isinstance(component, str) else None,
            project=project if isinstance(project, str) else None,
            severity=finding.severity,
            source_severity=source_severity if isinstance(source_severity, str) else None,
            automation_severity=finding.severity,
            branch_name=existing.branch_name if existing is not None else None,
            last_run_id=existing.last_run_id if existing is not None else None,
            status_updated_at=existing.status_updated_at if existing is not None else None,
            commit_sha=existing.commit_sha if existing is not None else None,
            change_request_number=existing.change_request_number if existing is not None else None,
            change_request_url=existing.change_request_url if existing is not None else None,
            upstream_active=True,
            log_excerpt=existing.log_excerpt if existing is not None else None,
        )

    def _dashboard_item_id(self, finding: NormalizedFinding) -> str:
        """Return the stable dashboard item id for one normalized SonarQube finding."""
        return f"sonar:{finding.finding_id}"


def _priority_from_severity(severity: str) -> str:
    """Map a normalized severity label to a dashboard priority string."""
    normalized = severity.upper()
    if normalized == "HIGH":
        return "high"
    if normalized == "MEDIUM":
        return "medium"
    return "low"
