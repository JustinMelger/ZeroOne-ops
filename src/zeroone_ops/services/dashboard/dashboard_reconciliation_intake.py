"""Dashboard reconciliation item intake service."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from zeroone_ops.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    normalize_dashboard_status,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService

_SKIP_REASON_MESSAGES = {
    "missing_branch_name": "without a stored branch name",
    "missing_commit_sha": "without a stored commit SHA",
    "missing_change_request_url": "without a linked change request URL",
    "unsupported_status": "with unsupported status",
}


@dataclass(frozen=True)
class DashboardReconciliationIntakeResult:
    """Capture the result of selecting reconciliation-ready dashboard items."""

    selected_items: list[DashboardItem]
    item_count: int
    message: str
    document: DashboardDocument

    @property
    def selected_item(self) -> DashboardItem | None:
        """Return the first selected item for backward-compatible callers."""
        if not self.selected_items:
            return None
        return self.selected_items[0]


class DashboardReconciliationIntakeService:
    """Load the dashboard and select one reconciliation-ready item."""

    def __init__(self, *, dashboard_service: DashboardService) -> None:
        """Initialize the dashboard reconciliation intake service."""
        self.dashboard_service = dashboard_service

    def select_item(self, *, project_id: str) -> DashboardReconciliationIntakeResult:
        """Load the dashboard and return the next eligible reconciliation item."""
        document = self.dashboard_service.load_or_create(project_id=project_id)
        items = [item for section in document.sections for item in section.items]
        selected_items = self._select_items(items)
        if not selected_items:
            return DashboardReconciliationIntakeResult(
                selected_items=[],
                item_count=len(items),
                message=self._build_no_item_message(
                    dashboard_issue_url=document.issue_url,
                    item_count=len(items),
                    skip_reason_counts=self._skip_reason_counts(items),
                ),
                document=document,
            )
        return DashboardReconciliationIntakeResult(
            selected_items=selected_items,
            item_count=len(items),
            message="",
            document=document,
        )

    def _select_items(self, items: list[DashboardItem]) -> list[DashboardItem]:
        """Return dashboard items that survive reconciliation checks."""
        return [item for item in items if self._skip_reason(item) is None]

    def _skip_reason_counts(self, items: list[DashboardItem]) -> Counter[str]:
        """Return skip-reason counts for the current dashboard item candidates."""
        skip_reason_counts: Counter[str] = Counter()
        for item in items:
            skip_reason = self._skip_reason(item)
            if skip_reason is not None:
                skip_reason_counts[skip_reason] += 1
        return skip_reason_counts

    def _skip_reason(self, item: DashboardItem) -> str | None:
        """Return the stable reason one dashboard item should be skipped."""
        if normalize_dashboard_status(item.status) != "change_request_opened":
            return "unsupported_status"
        if item.change_request_url is None:
            return "missing_change_request_url"
        if item.branch_name is None:
            return "missing_branch_name"
        if item.commit_sha is None:
            return "missing_commit_sha"
        return None

    def _build_no_item_message(
        self,
        *,
        dashboard_issue_url: str,
        item_count: int,
        skip_reason_counts: Counter[str],
    ) -> str:
        """Build a CLI-facing no-item summary."""
        message = (
            "No reconciliation-ready dashboard item found in "
            f"{dashboard_issue_url} from {item_count} parsed dashboard items."
        )
        if not skip_reason_counts:
            return message
        reason_parts = [
            f"skipped {count} items {_SKIP_REASON_MESSAGES[reason]}"
            for reason, count in sorted(skip_reason_counts.items())
        ]
        return f"{message} " + "; ".join(reason_parts) + "."
