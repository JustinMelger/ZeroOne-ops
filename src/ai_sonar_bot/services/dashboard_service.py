"""Dashboard orchestration service."""

from __future__ import annotations

from ai_sonar_bot.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    DashboardSection,
    DashboardSectionKey,
    empty_sections,
    section_key_for_item,
)
from ai_sonar_bot.providers.gitlab_dashboard_client import GitLabDashboardClient
from ai_sonar_bot.services.dashboard_parser import DashboardParser
from ai_sonar_bot.services.dashboard_renderer import DashboardRenderer

DEFAULT_SECTION_ITEM_LIMITS: dict[DashboardSectionKey, int] = {
    "open_candidates": 50,
    "in_progress": 25,
    "merge_requests_opened": 25,
    "merge_request_reviews": 25,
    "rejected_or_ignored": 25,
    "recent_failures": 25,
}


class DashboardService:
    """Load, create, merge, and publish the dashboard issue."""

    def __init__(
        self,
        client: GitLabDashboardClient,
        *,
        parser: DashboardParser | None = None,
        renderer: DashboardRenderer | None = None,
        title: str = "AI Code Ops Dashboard",
        labels: list[str] | None = None,
        section_item_limits: dict[DashboardSectionKey, int] | None = None,
    ) -> None:
        """Initialize the dashboard service."""
        self.client = client
        self.parser = parser or DashboardParser()
        self.renderer = renderer or DashboardRenderer()
        self.title = title
        self.labels = labels or ["ai-code-ops", "dashboard"]
        self.section_item_limits = section_item_limits or DEFAULT_SECTION_ITEM_LIMITS.copy()

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        """Load the dashboard issue or create it if missing."""
        issue = self.client.find_open_issue(
            project_id=project_id,
            title=self.title,
            labels=self.labels,
        )
        if issue is None:
            body = self.renderer.render(title=self.title, sections=empty_sections())
            issue = self.client.create_issue(
                project_id=project_id,
                title=self.title,
                description=body,
                labels=self.labels,
            )
        return self.parser.parse(
            issue_id=issue.id,
            issue_iid=issue.iid,
            issue_url=issue.web_url,
            title=issue.title,
            body=issue.description,
        )

    def upsert_items(
        self,
        *,
        project_id: str,
        items: list[DashboardItem],
    ) -> DashboardDocument:
        """Upsert dashboard items and publish the updated issue."""
        document = self.load_or_create(project_id=project_id)
        merged_document = self._merge_items(document=document, items=items)
        rendered = self.renderer.render_document(merged_document)
        issue = self.client.update_issue(
            project_id=project_id,
            issue_iid=merged_document.issue_iid,
            description=rendered,
        )
        return self.parser.parse(
            issue_id=issue.id,
            issue_iid=issue.iid,
            issue_url=issue.web_url,
            title=issue.title,
            body=issue.description,
        )

    def _merge_items(
        self,
        *,
        document: DashboardDocument,
        items: list[DashboardItem],
    ) -> DashboardDocument:
        existing = document.items_by_id()
        for item in items:
            existing[item.id] = item
        sections_by_key: dict[str, list[DashboardItem]] = {
            section.key: [] for section in empty_sections()
        }
        for item in sorted(existing.values(), key=_item_sort_key):
            sections_by_key[section_key_for_item(item)].append(item)
        sections = [
            DashboardSection(
                key=section.key,
                title=section.title,
                items=self._apply_retention(
                    section.key,
                    sections_by_key[section.key],
                ),
            )
            for section in empty_sections()
        ]
        return DashboardDocument(
            issue_id=document.issue_id,
            issue_iid=document.issue_iid,
            issue_url=document.issue_url,
            title=document.title,
            sections=sections,
        )

    def _apply_retention(
        self,
        section_key: DashboardSectionKey,
        items: list[DashboardItem],
    ) -> list[DashboardItem]:
        """Bound the number of rendered items for one dashboard section."""
        limit = self.section_item_limits.get(section_key)
        if limit is None or limit <= 0:
            return items
        return items[:limit]


def _item_sort_key(item: DashboardItem) -> tuple[str, str, str, str]:
    """Sort dashboard items deterministically within sections."""
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return (str(priority_order.get(item.priority, 99)), item.source, item.type, item.id)
