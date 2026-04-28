"""Dashboard orchestration service."""

from __future__ import annotations

from zeroone_ops.models.dashboard import (
    CURRENT_DASHBOARD_SCHEMA_VERSION,
    DashboardDocument,
    DashboardItem,
    DashboardSection,
    DashboardSectionKey,
    empty_sections,
    section_key_for_item,
)
from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient
from zeroone_ops.services.dashboard.dashboard_parser import DashboardParser
from zeroone_ops.services.dashboard.dashboard_policy_action_service import (
    DashboardPolicyActionService,
)
from zeroone_ops.services.dashboard.dashboard_policy_service import (
    DashboardPolicyService,
    DashboardPolicyViewBuilderProtocol,
)
from zeroone_ops.services.dashboard.dashboard_renderer import DashboardRenderer

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
        title: str = "AI Code Ops Work Queue",
        labels: list[str] | None = None,
        section_item_limits: dict[DashboardSectionKey, int] | None = None,
        policy_view_builder: DashboardPolicyViewBuilderProtocol | None = None,
        policy_action_service: DashboardPolicyActionService | None = None,
    ) -> None:
        """Initialize the dashboard service."""
        self.client = client
        self.parser = parser or DashboardParser()
        self.renderer = renderer or DashboardRenderer()
        self.title = title
        self.labels = labels or ["ai-code-ops", "dashboard"]
        self.section_item_limits = section_item_limits or DEFAULT_SECTION_ITEM_LIMITS.copy()
        self.policy_service = DashboardPolicyService(
            policy_view_builder=policy_view_builder,
            policy_action_service=policy_action_service or DashboardPolicyActionService(),
        )

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        """Load the dashboard issue or create it if missing."""
        issue = self.client.find_open_issue(
            project_id=project_id,
            title=self.title,
            labels=self.labels,
        )
        if issue is None:
            document = self._apply_policy(
                DashboardDocument(
                    issue_id=0,
                    issue_iid=0,
                    issue_url="",
                    title=self.title,
                    sections=empty_sections(),
                )
            )
            body = self.renderer.render_document(document)
            issue = self.client.create_issue(
                project_id=project_id,
                title=self.title,
                description=body,
                labels=self.labels,
            )
            return document.model_copy(
                update={
                    "issue_id": issue.id,
                    "issue_iid": issue.iid,
                    "issue_url": issue.web_url,
                    "title": issue.title,
                }
            )
        document = self.parser.parse(
            issue_id=issue.id,
            issue_iid=issue.iid,
            issue_url=issue.web_url,
            title=issue.title,
            body=issue.description,
        )
        notes = self.client.list_issue_notes(
            project_id=project_id,
            issue_iid=document.issue_iid,
        )
        document = self._apply_policy(document, notes=notes)
        rendered = self.renderer.render_document(document)
        if (
            rendered != issue.description
            or document.schema_version != CURRENT_DASHBOARD_SCHEMA_VERSION
        ):
            issue = self.client.update_issue(
                project_id=project_id,
                issue_iid=document.issue_iid,
                description=rendered,
            )
            return document.model_copy(
                update={
                    "issue_id": issue.id,
                    "issue_iid": issue.iid,
                    "issue_url": issue.web_url,
                    "title": issue.title,
                    "schema_version": CURRENT_DASHBOARD_SCHEMA_VERSION,
                }
            )
        return document

    def upsert_items(
        self,
        *,
        project_id: str,
        items: list[DashboardItem],
    ) -> DashboardDocument:
        """Upsert dashboard items and publish the updated issue."""
        document = self.load_or_create(project_id=project_id)
        merged_document = self._merge_items(document=document, items=items)
        merged_document = self._apply_policy(merged_document)
        rendered = self.renderer.render_document(merged_document)
        issue = self.client.update_issue(
            project_id=project_id,
            issue_iid=merged_document.issue_iid,
            description=rendered,
        )
        return merged_document.model_copy(
            update={
                "issue_id": issue.id,
                "issue_iid": issue.iid,
                "issue_url": issue.web_url,
                "title": issue.title,
                "schema_version": CURRENT_DASHBOARD_SCHEMA_VERSION,
            }
        )

    def _apply_policy(
        self,
        document: DashboardDocument,
        *,
        notes: list[GitLabIssueNote] | None = None,
    ) -> DashboardDocument:
        """Apply canonical dashboard policy state and rendered view to one document."""
        updated = self.policy_service.apply_to_document(document, notes=notes)
        return updated.model_copy(update={"schema_version": CURRENT_DASHBOARD_SCHEMA_VERSION})

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
            schema_version=document.schema_version,
            policy_state=document.policy_state,
            policy_view=document.policy_view,
        )

    def _apply_policy_actions(
        self,
        document: DashboardDocument,
        *,
        project_id: str,
    ) -> DashboardDocument:
        """Replay policy issue-note actions into canonical dashboard policy state."""
        if self.policy_view_builder is None:
            return document
        notes = self.client.list_issue_notes(
            project_id=project_id,
            issue_iid=document.issue_iid,
        )
        seeded_policy_state = self.policy_view_builder.resolve_policy_state(document.policy_state)
        policy_state = self.policy_action_service.apply_actions(
            policy_state=seeded_policy_state,
            notes=notes,
        )
        return document.model_copy(update={"policy_state": policy_state})

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
