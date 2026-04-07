"""Dashboard remediation item intake service."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.dashboard import DashboardDocument, DashboardItem
from ai_sonar_bot.models.state import AppState
from ai_sonar_bot.services.dashboard_item_selector import DashboardItemSelector
from ai_sonar_bot.services.dashboard_service import DashboardService

LOGGER = logging.getLogger(__name__)

_SKIP_REASON_MESSAGES = {
    "active_local_state": "already tracked as active locally",
    "missing_file_path": "without a target file path",
    "missing_local_file": "without a matching local file",
    "unsupported_source": "from unsupported sources",
    "unsupported_status": "with unsupported status",
    "unsupported_type": "with unsupported type",
}


@dataclass(frozen=True)
class DashboardItemIntakeResult:
    """Capture the result of selecting one dashboard remediation item."""

    selected_item: DashboardItem | None
    item_count: int
    message: str
    document: DashboardDocument


class DashboardItemIntakeService:
    """Load the dashboard and select one remediation-ready item."""

    def __init__(
        self,
        *,
        repo_root: Path,
        dashboard_service: DashboardService,
        selector: DashboardItemSelector | None = None,
    ) -> None:
        """Initialize the dashboard item intake service."""
        self.dashboard_service = dashboard_service
        self.selector = selector or DashboardItemSelector(repo_root=repo_root)

    def select_item(
        self,
        *,
        project_id: str,
        state: AppState,
    ) -> DashboardItemIntakeResult:
        """Load the dashboard and return the next eligible remediation item."""
        document = self.dashboard_service.load_or_create(project_id=project_id)
        items = [item for section in document.sections for item in section.items]
        skip_reason_counts = self._skip_reason_counts(items, state)
        selected_item = self.selector.select(items, state)
        if selected_item is None:
            return DashboardItemIntakeResult(
                selected_item=None,
                item_count=len(items),
                message=self._build_no_item_message(
                    dashboard_issue_url=document.issue_url,
                    item_count=len(items),
                    skip_reason_counts=skip_reason_counts,
                ),
                document=document,
            )
        return DashboardItemIntakeResult(
            selected_item=selected_item,
            item_count=len(items),
            message="",
            document=document,
        )

    def _skip_reason_counts(self, items: list[DashboardItem], state: AppState) -> Counter[str]:
        """Return skip-reason counts for the current dashboard item candidates."""
        skip_reason_counts: Counter[str] = Counter()
        for item in items:
            skip_reason = self.selector.skip_reason(item, state)
            if skip_reason is None:
                continue
            skip_reason_counts[skip_reason] += 1
            LOGGER.info(
                "skipped dashboard remediation item during intake",
                extra={"dashboard_item_id": item.id, "reason": skip_reason},
            )
        return skip_reason_counts

    def _build_no_item_message(
        self,
        *,
        dashboard_issue_url: str,
        item_count: int,
        skip_reason_counts: Counter[str],
    ) -> str:
        """Build the no-item-selected summary message."""
        if item_count == 0:
            return f"No remediation-ready dashboard item found in {dashboard_issue_url}."
        if not skip_reason_counts:
            return (
                "No remediation-ready dashboard item selected from "
                f"{item_count} dashboard items in {dashboard_issue_url}."
            )
        reason_summary = ", ".join(
            f"{count} {self._describe_skip_reason(reason)}"
            for reason, count in sorted(skip_reason_counts.items())
        )
        return (
            "No remediation-ready dashboard item selected from "
            f"{item_count} dashboard items in {dashboard_issue_url}: {reason_summary}."
        )

    def _describe_skip_reason(self, reason: str) -> str:
        """Return a human-readable label for one stable skip reason."""
        return _SKIP_REASON_MESSAGES.get(reason, reason.replace("_", " "))
