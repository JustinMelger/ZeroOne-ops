"""Dashboard remediation item selection rules."""

from __future__ import annotations

from pathlib import Path

from zeroone_ops.models.dashboard import DashboardItem, normalize_dashboard_status
from zeroone_ops.models.state import AppState

ACTIVE_DASHBOARD_ITEM_STATUSES = frozenset({"in_progress", "change_request_opened"})
SUPPORTED_REMEDIATION_ITEM_TYPES = frozenset({"code_smell_fix"})
SUPPORTED_REMEDIATION_SOURCES = frozenset({"sonarqube"})


class DashboardItemSelector:
    """Select one remediation-ready dashboard item for a run."""

    def __init__(self, *, repo_root: Path) -> None:
        """Initialize the selector."""
        self.repo_root = repo_root

    def select(self, items: list[DashboardItem], state: AppState) -> DashboardItem | None:
        """Return the first eligible dashboard item."""
        for item in items:
            if self.skip_reason(item, state) is None:
                return item
        return None

    def skip_reason(self, item: DashboardItem, state: AppState) -> str | None:
        """Return the stable reason one dashboard item should be skipped."""
        if item.status != "open":
            return "unsupported_status"
        if item.type not in SUPPORTED_REMEDIATION_ITEM_TYPES:
            return "unsupported_type"
        if item.source not in SUPPORTED_REMEDIATION_SOURCES:
            return "unsupported_source"
        if item.file is None:
            return "missing_file_path"
        if (
            item.review_status is not None
            and item.retry_eligible is False
            and item.retry_block_reason
        ):
            return "retry_blocked"
        if not (self.repo_root / item.file).exists():
            return "missing_local_file"
        if state.active_dashboard_item_id == item.id:
            return "active_local_state"
        dashboard_item_state = state.dashboard_items.get(item.id)
        if (
            dashboard_item_state is not None
            and normalize_dashboard_status(dashboard_item_state.status)
            in ACTIVE_DASHBOARD_ITEM_STATUSES
        ):
            return "active_local_state"
        return None
