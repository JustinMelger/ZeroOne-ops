"""SonarQube discovery mirroring to the dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from ai_sonar_bot.models.dashboard import DashboardDocument, DashboardItem
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.services.dashboard_service import DashboardService

_ACTIVE_SONAR_STATUSES = frozenset({"open", "in_progress", "mr_opened"})


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
        issues: list[SonarIssue],
    ) -> SonarDashboardSyncResult:
        """Upsert eligible SonarQube issues into the dashboard."""
        document = self.dashboard_service.load_or_create(project_id=project_id)
        items = self._build_reconciled_items(document=document, issues=issues)
        document = self.dashboard_service.upsert_items(project_id=project_id, items=items)
        return SonarDashboardSyncResult(
            synced_count=len(issues),
            dashboard_issue_url=document.issue_url,
        )

    def _build_reconciled_items(
        self,
        *,
        document: DashboardDocument,
        issues: list[SonarIssue],
    ) -> list[DashboardItem]:
        """Return current Sonar items plus stale-item reconciliation updates."""
        existing_items = document.items_by_id()
        current_issue_ids = {f"sonar:{issue.key}" for issue in issues}
        items = [
            self._normalize_issue(issue, existing=existing_items.get(f"sonar:{issue.key}"))
            for issue in issues
        ]
        for item in existing_items.values():
            if (
                item.source == "sonarqube"
                and item.id not in current_issue_ids
                and item.status in _ACTIVE_SONAR_STATUSES
            ):
                items.append(item.model_copy(update={"status": "done"}))
        return items

    def _normalize_issue(
        self,
        issue: SonarIssue,
        *,
        existing: DashboardItem | None = None,
    ) -> DashboardItem:
        """Normalize one SonarQube issue into a dashboard item."""
        return DashboardItem(
            id=f"sonar:{issue.key}",
            source="sonarqube",
            type=existing.type if existing is not None else "code_smell_fix",
            status=existing.status if existing is not None else "open",
            title=f"{issue.rule} in {issue.file_path}",
            summary=issue.message,
            priority=_priority_from_issue(issue),
            source_reference=issue.key,
            file=issue.file_path,
            line=issue.line,
            rule=issue.rule,
            severity=issue.severity,
        )


def _priority_from_issue(issue: SonarIssue) -> str:
    """Map a SonarQube issue to a dashboard priority string."""
    normalized = issue.severity.upper()
    if normalized in {"BLOCKER", "CRITICAL", "HIGH"}:
        return "high"
    if normalized in {"MAJOR", "MEDIUM"}:
        return "medium"
    return "low"
