"""Dashboard remediation item intake service."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    DashboardPolicyState,
    DashboardSeverityPolicyStateEntry,
)
from zeroone_ops.models.state import AppState
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.dashboard.dashboard_item_selector import (
    DashboardItemSelector,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.shared.change_request_lookup import (
    ChangeRequestLookup,
    build_change_request_lookup,
)
from zeroone_ops.settings import SettingsError
from zeroone_ops.utils.git import build_issue_branch_name

LOGGER = logging.getLogger(__name__)
_STALE_IN_PROGRESS_WINDOW = timedelta(hours=24)
_DEFAULT_ENABLED_SEVERITIES: frozenset[str] = frozenset({"low", "medium"})

_SKIP_REASON_MESSAGES = {
    "active_local_state": "already tracked as active locally",
    "active_merge_request": "already represented by an active change request",
    "blocked_by_severity_policy": "blocked by severity policy",
    "excluded_by_policy": "explicitly excluded from automation",
    "missing_file_path": "without a target file path",
    "missing_local_file": "without a matching local file",
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
        change_request_lookup: ChangeRequestLookup | None = None,
    ) -> None:
        """Initialize the dashboard item intake service."""
        self.repo_root = repo_root
        self.config = config
        self.dashboard_service = dashboard_service
        self.selector = selector or DashboardItemSelector(repo_root=repo_root)
        self.change_request_lookup = change_request_lookup

    def select_item(
        self,
        *,
        project_id: str,
        state: AppState,
    ) -> DashboardItemIntakeResult:
        """Load the dashboard and return the next eligible remediation item."""
        document = self.dashboard_service.load_or_create(project_id=project_id)
        policy_state = self._resolved_policy_state(document.policy_state)
        document = document.model_copy(update={"policy_state": policy_state})
        document, recovered_stale_item_ids = self._recover_stale_in_progress_items(
            document=document,
            project_id=project_id,
        )
        document = document.model_copy(
            update={"policy_state": self._resolved_policy_state(document.policy_state)}
        )
        items = [item for section in document.sections for item in section.items]
        change_request_lookup = self._build_change_request_lookup()
        skip_reason_counts = self._skip_reason_counts(
            items,
            state,
            policy_state=document.policy_state,
            change_request_lookup=change_request_lookup,
        )
        selected_item = self._select_item(
            items,
            state,
            policy_state=document.policy_state,
            change_request_lookup=change_request_lookup,
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
        policy_state: DashboardPolicyState,
        change_request_lookup: ChangeRequestLookup | None,
    ) -> Counter[str]:
        """Return skip-reason counts for the current dashboard item candidates."""
        skip_reason_counts: Counter[str] = Counter()
        for item in items:
            skip_reason = self._skip_reason(
                item,
                state,
                policy_state=policy_state,
                change_request_lookup=change_request_lookup,
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
        policy_state: DashboardPolicyState,
        change_request_lookup: ChangeRequestLookup | None,
    ) -> DashboardItem | None:
        """Return the first dashboard item that survives intake checks."""
        for item in items:
            if (
                self._skip_reason(
                    item,
                    state,
                    policy_state=policy_state,
                    change_request_lookup=change_request_lookup,
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
        policy_state: DashboardPolicyState,
        change_request_lookup: ChangeRequestLookup | None,
    ) -> str | None:
        """Return the stable reason one dashboard item should be skipped."""
        selector_reason = self.selector.skip_reason(item, state)
        if selector_reason is not None:
            return selector_reason
        if self._is_blocked_by_severity_policy(item, policy_state=policy_state):
            return "blocked_by_severity_policy"
        if self._is_excluded_by_dashboard_policy(item, policy_state=policy_state):
            return "excluded_by_policy"
        return self._active_merge_request_skip_reason(
            item,
            change_request_lookup=change_request_lookup,
        )

    def _is_blocked_by_severity_policy(
        self,
        item: DashboardItem,
        *,
        policy_state: DashboardPolicyState,
    ) -> bool:
        """Return whether one dashboard item is blocked by canonical severity policy."""
        automation_severity = (item.automation_severity or item.severity or "").lower()
        if not automation_severity:
            return False
        enabled = {
            entry.severity.lower() for entry in policy_state.severity_policy if entry.enabled
        }
        return automation_severity not in enabled

    def _resolved_policy_state(
        self,
        policy_state: DashboardPolicyState,
    ) -> DashboardPolicyState:
        """Return the effective severity policy for intake when the document lacks one."""
        if policy_state.severity_policy:
            return policy_state
        if self.config is None:
            return DashboardPolicyState(
                severity_policy=[
                    DashboardSeverityPolicyStateEntry(severity="low", enabled=True),
                    DashboardSeverityPolicyStateEntry(severity="medium", enabled=True),
                    DashboardSeverityPolicyStateEntry(
                        severity="high",
                        enabled=False,
                        reason="Disabled by current config baseline.",
                        updated_by="config_seed",
                    ),
                ]
            )
        enabled = {
            severity.lower() for severity in self.config.remediation.bootstrap_severities
        } or set(_DEFAULT_ENABLED_SEVERITIES)
        return DashboardPolicyState(
            severity_policy=[
                DashboardSeverityPolicyStateEntry(
                    severity="low",
                    enabled="low" in enabled,
                    reason=None if "low" in enabled else "Disabled by current config baseline.",
                    updated_by="config_seed",
                ),
                DashboardSeverityPolicyStateEntry(
                    severity="medium",
                    enabled="medium" in enabled,
                    reason=(
                        None if "medium" in enabled else "Disabled by current config baseline."
                    ),
                    updated_by="config_seed",
                ),
                DashboardSeverityPolicyStateEntry(
                    severity="high",
                    enabled="high" in enabled,
                    reason=(None if "high" in enabled else "Disabled by current config baseline."),
                    updated_by="config_seed",
                ),
            ]
        )

    def _is_excluded_by_dashboard_policy(
        self,
        item: DashboardItem,
        *,
        policy_state: DashboardPolicyState,
    ) -> bool:
        """Return whether one dashboard item matches canonical dashboard exclusion policy."""
        issue_key = item.rule
        if issue_key is None:
            return False
        return any(
            exclusion.source == item.source and exclusion.issue_key == issue_key
            for exclusion in policy_state.issue_class_exclusions
        )

    def _active_merge_request_skip_reason(
        self,
        item: DashboardItem,
        *,
        change_request_lookup: ChangeRequestLookup | None,
    ) -> str | None:
        """Return whether one dashboard item is already represented by an open MR."""
        if item.change_request_url:
            return "active_merge_request"
        if self.config is None or change_request_lookup is None or item.file is None:
            return None
        branch_name = item.branch_name or build_issue_branch_name(
            branch_prefix=self.config.branch_prefix,
            issue_key=item.source_reference,
            file_path=item.file,
        )
        target_branch = self.config.require_remediation_target_branch(
            reason="Dashboard review intake",
        )
        existing_merge_request = change_request_lookup.find_open_change_request(
            source_branch=branch_name,
            target_branch=target_branch,
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

    def _build_change_request_lookup(self) -> ChangeRequestLookup | None:
        """Return the configured change-request lookup when provider state is available."""
        if self.change_request_lookup is not None:
            return self.change_request_lookup
        if self.config is None:
            return None
        try:
            return build_change_request_lookup(self.config)
        except (GitLabClientError, SettingsError):
            return None

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
