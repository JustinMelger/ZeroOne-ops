"""Dashboard remediation item intake service."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ai_sonar_bot.models.config import AppConfig, GitLabConnectionConfig
from ai_sonar_bot.models.dashboard import DashboardDocument, DashboardItem
from ai_sonar_bot.models.state import AppState
from ai_sonar_bot.providers.gitlab_client import GitLabClient
from ai_sonar_bot.services.dashboard.dashboard_item_selector import (
    DashboardItemSelector,
)
from ai_sonar_bot.services.dashboard.dashboard_service import DashboardService
from ai_sonar_bot.services.mr_service import MergeRequestService
from ai_sonar_bot.services.remediation.remediation_exclusion_service import (
    RemediationExclusionService,
)
from ai_sonar_bot.settings import SettingsError, load_gitlab_connection_config
from ai_sonar_bot.utils.git import build_issue_branch_name

LOGGER = logging.getLogger(__name__)
_STALE_IN_PROGRESS_WINDOW = timedelta(hours=24)

_SKIP_REASON_MESSAGES = {
    "active_local_state": "already tracked as active locally",
    "active_merge_request": "already represented by an active merge request",
    "excluded_by_policy": "explicitly excluded from automation",
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
    recovered_stale_item_ids: tuple[str, ...] = ()


class DashboardItemIntakeService:
    """Load the dashboard and select one remediation-ready item."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig | None = None,
        dashboard_service: DashboardService,
        selector: DashboardItemSelector | None = None,
        merge_request_service: MergeRequestService | None = None,
    ) -> None:
        """Initialize the dashboard item intake service."""
        self.repo_root = repo_root
        self.config = config
        self.dashboard_service = dashboard_service
        self.selector = selector or DashboardItemSelector(repo_root=repo_root)
        self.merge_request_service = merge_request_service

    def select_item(
        self,
        *,
        project_id: str,
        state: AppState,
    ) -> DashboardItemIntakeResult:
        """Load the dashboard and return the next eligible remediation item."""
        document = self.dashboard_service.load_or_create(project_id=project_id)
        document, recovered_stale_item_ids = self._recover_stale_in_progress_items(
            document=document,
            project_id=project_id,
        )
        items = [item for section in document.sections for item in section.items]
        exclusion_service = self._build_exclusion_service(state)
        gitlab_config = self._load_gitlab_config()
        merge_request_service = self._build_merge_request_service(gitlab_config)
        skip_reason_counts = self._skip_reason_counts(
            items,
            state,
            exclusion_service=exclusion_service,
            gitlab_config=gitlab_config,
            merge_request_service=merge_request_service,
        )
        selected_item = self._select_item(
            items,
            state,
            exclusion_service=exclusion_service,
            gitlab_config=gitlab_config,
            merge_request_service=merge_request_service,
        )
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
                recovered_stale_item_ids=recovered_stale_item_ids,
            )
        return DashboardItemIntakeResult(
            selected_item=selected_item,
            item_count=len(items),
            message="",
            document=document,
            recovered_stale_item_ids=recovered_stale_item_ids,
        )

    def _skip_reason_counts(
        self,
        items: list[DashboardItem],
        state: AppState,
        *,
        exclusion_service: RemediationExclusionService,
        gitlab_config: GitLabConnectionConfig | None,
        merge_request_service: MergeRequestService | None,
    ) -> Counter[str]:
        """Return skip-reason counts for the current dashboard item candidates."""
        skip_reason_counts: Counter[str] = Counter()
        for item in items:
            skip_reason = self._skip_reason(
                item,
                state,
                exclusion_service=exclusion_service,
                gitlab_config=gitlab_config,
                merge_request_service=merge_request_service,
            )
            if skip_reason is None:
                continue
            skip_reason_counts[skip_reason] += 1
            LOGGER.info(
                "skipped dashboard remediation item during intake",
                extra={
                    "dashboard_item_id": item.id,
                    "reason": skip_reason,
                    "source": item.source,
                    "issue_key": item.rule or item.source_reference,
                    "file": item.file,
                },
            )
        return skip_reason_counts

    def _select_item(
        self,
        items: list[DashboardItem],
        state: AppState,
        *,
        exclusion_service: RemediationExclusionService,
        gitlab_config: GitLabConnectionConfig | None,
        merge_request_service: MergeRequestService | None,
    ) -> DashboardItem | None:
        """Return the first dashboard item that survives intake checks."""
        for item in items:
            if (
                self._skip_reason(
                    item,
                    state,
                    exclusion_service=exclusion_service,
                    gitlab_config=gitlab_config,
                    merge_request_service=merge_request_service,
                )
                is None
            ):
                return item
        return None

    def _skip_reason(
        self,
        item: DashboardItem,
        state: AppState,
        *,
        exclusion_service: RemediationExclusionService,
        gitlab_config: GitLabConnectionConfig | None,
        merge_request_service: MergeRequestService | None,
    ) -> str | None:
        """Return the stable reason one dashboard item should be skipped."""
        selector_reason = self.selector.skip_reason(item, state)
        if selector_reason is not None:
            return selector_reason
        if exclusion_service.matches_dashboard_item(item):
            return "excluded_by_policy"
        return self._active_merge_request_skip_reason(
            item,
            gitlab_config=gitlab_config,
            merge_request_service=merge_request_service,
        )

    def _active_merge_request_skip_reason(
        self,
        item: DashboardItem,
        *,
        gitlab_config: GitLabConnectionConfig | None,
        merge_request_service: MergeRequestService | None,
    ) -> str | None:
        """Return whether one dashboard item is already represented by an open MR."""
        if item.merge_request_url:
            return "active_merge_request"
        if (
            self.config is None
            or gitlab_config is None
            or merge_request_service is None
            or item.source != "sonarqube"
            or item.file is None
        ):
            return None
        branch_name = item.branch_name or build_issue_branch_name(
            branch_prefix=self.config.branch_prefix,
            issue_key=item.source_reference,
            file_path=item.file,
        )
        existing_merge_request = merge_request_service.find_open(
            project_id=gitlab_config.project_id,
            source_branch=branch_name,
            target_branch=self.config.gitlab.target_branch,
        )
        if existing_merge_request is None:
            return None
        return "active_merge_request"

    def _recover_stale_in_progress_items(
        self,
        *,
        document: DashboardDocument,
        project_id: str,
    ) -> tuple[DashboardDocument, tuple[str, ...]]:
        """Reopen stale in-progress items before selection."""
        recovered_items = [
            self._recover_stale_item(item)
            for item in document.items_by_id().values()
            if self._is_stale_in_progress_item(item)
        ]
        if not recovered_items:
            return document, ()
        updated_document = self.dashboard_service.upsert_items(
            project_id=project_id,
            items=recovered_items,
        )
        return updated_document, tuple(item.id for item in recovered_items)

    def _recover_stale_item(self, item: DashboardItem) -> DashboardItem:
        """Return the recovered version of one stale in-progress item."""
        recovered_at = datetime.now(UTC)
        stale_reference = (
            item.status_updated_at.isoformat() if item.status_updated_at else "unknown"
        )
        log_excerpt = (
            f"Reopened after stale in_progress recovery. Last active update was {stale_reference}."
        )
        return item.model_copy(
            update={
                "status": "open",
                "status_updated_at": recovered_at,
                "log_excerpt": log_excerpt,
            }
        )

    def _is_stale_in_progress_item(self, item: DashboardItem) -> bool:
        """Return whether one in-progress item should be reopened."""
        if item.status != "in_progress":
            return False
        if item.last_run_id is None or item.status_updated_at is None:
            return False
        return item.status_updated_at <= datetime.now(UTC) - _STALE_IN_PROGRESS_WINDOW

    def _load_gitlab_config(self) -> GitLabConnectionConfig | None:
        """Load GitLab config when remote duplicate lookup is available."""
        try:
            return load_gitlab_connection_config()
        except SettingsError:
            return None

    def _build_merge_request_service(
        self,
        gitlab_config: GitLabConnectionConfig | None,
    ) -> MergeRequestService | None:
        """Return the configured merge request lookup service when available."""
        if self.merge_request_service is not None:
            return self.merge_request_service
        if gitlab_config is None:
            return None
        return MergeRequestService(GitLabClient(gitlab_config))

    def _build_exclusion_service(self, state: AppState) -> RemediationExclusionService:
        """Return one read-only exclusion matcher for remediation intake."""
        return RemediationExclusionService(state_store=None, state=state)

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
