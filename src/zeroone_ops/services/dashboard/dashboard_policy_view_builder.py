"""Build read-only dashboard operator-policy views."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Literal

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.dashboard import (
    DashboardAutomationStatus,
    DashboardIssueClassExclusionEntry,
    DashboardIssueClassInventoryEntry,
    DashboardItem,
    DashboardPolicyView,
    DashboardSeverityPolicyEntry,
)
from zeroone_ops.models.state import AppState
from zeroone_ops.services.dashboard.dashboard_item_selector import DashboardItemSelector
from zeroone_ops.services.remediation.remediation_exclusion_service import (
    RemediationExclusionService,
)

_SEVERITY_ORDER: tuple[Literal["low", "medium", "high"], ...] = ("low", "medium", "high")
_TOP_ACTIVE_GROUP_LIMIT = 5
_SAFETY_SKIP_REASONS = frozenset(
    {
        "missing_file_path",
        "missing_local_file",
        "retry_blocked",
        "unsupported_source",
        "unsupported_type",
    }
)


class DashboardPolicyViewBuilder:
    """Build a read-only policy view from current config, state, and dashboard items."""

    def __init__(
        self,
        *,
        repo_root: Path,
        config: AppConfig,
        state: AppState,
    ) -> None:
        """Initialize the policy-view builder."""
        self.repo_root = repo_root
        self.config = config
        self.state = state
        self.selector = DashboardItemSelector(repo_root=repo_root)
        self.exclusion_service = RemediationExclusionService(state_store=None, state=state)

    def build(self, items: list[DashboardItem]) -> DashboardPolicyView:
        """Return the rendered read-only policy view for current dashboard items."""
        return DashboardPolicyView(
            severity_policy=self._build_severity_policy(),
            excluded_issue_classes=self._build_excluded_issue_classes(items),
            issue_class_inventory=self._build_issue_class_inventory(items),
        )

    def _build_severity_policy(self) -> list[DashboardSeverityPolicyEntry]:
        enabled = {severity.lower() for severity in self.config.remediation.supported_severities}
        return [
            DashboardSeverityPolicyEntry(
                severity=severity,
                enabled=severity in enabled,
                reason=None if severity in enabled else "Disabled by current config baseline.",
            )
            for severity in _SEVERITY_ORDER
        ]

    def _build_excluded_issue_classes(
        self,
        items: list[DashboardItem],
    ) -> list[DashboardIssueClassExclusionEntry]:
        grouped: list[DashboardIssueClassExclusionEntry] = []
        for exclusion in self.exclusion_service.list_exclusions():
            matching_count = sum(
                1
                for item in items
                if self.exclusion_service.matches_dashboard_item(item)
                and item.source == exclusion.source
                and self._issue_key_for_item(item) == exclusion.issue_key
            )
            grouped.append(
                DashboardIssueClassExclusionEntry(
                    source=exclusion.source,
                    issue_key=exclusion.issue_key,
                    matching_items_count=matching_count,
                    reason=exclusion.reason,
                )
            )
        return grouped

    def _build_issue_class_inventory(
        self,
        items: list[DashboardItem],
    ) -> list[DashboardIssueClassInventoryEntry]:
        grouped_items: dict[tuple[str, str], list[DashboardItem]] = defaultdict(list)
        for item in items:
            if item.status != "open":
                continue
            issue_key = self._issue_key_for_item(item)
            if issue_key is None:
                continue
            grouped_items[(item.source, issue_key)].append(item)

        if not grouped_items:
            return []

        excluded_keys = {
            (exclusion.source, exclusion.issue_key)
            for exclusion in self.exclusion_service.list_exclusions()
        }
        blocked_severity_keys = {
            key
            for key, grouped in grouped_items.items()
            if self._all_items_blocked_by_severity(grouped)
        }
        sorted_keys = sorted(
            grouped_items,
            key=lambda key: (-len(grouped_items[key]), key[0], key[1]),
        )
        selected_keys: list[tuple[str, str]] = []
        priority_keys = excluded_keys | blocked_severity_keys
        for key in sorted_keys:
            if key in priority_keys:
                selected_keys.append(key)
        additional_limit = len(priority_keys) + _TOP_ACTIVE_GROUP_LIMIT
        for key in sorted_keys:
            if key in selected_keys:
                continue
            if len(selected_keys) >= additional_limit:
                break
            selected_keys.append(key)

        inventory: list[DashboardIssueClassInventoryEntry] = []
        for key in selected_keys:
            source, issue_key = key
            grouped = grouped_items[key]
            status, reason = self._group_status(grouped)
            normalized_severities = {
                severity
                for item in grouped
                for severity in [self._automation_severity_for_item(item)]
                if severity is not None
            }
            severities = sorted(
                normalized_severities,
                key=(
                    lambda severity: (
                        _SEVERITY_ORDER.index(severity) if severity in _SEVERITY_ORDER else 99
                    )
                ),
            )
            inventory.append(
                DashboardIssueClassInventoryEntry(
                    source=source,
                    issue_key=issue_key,
                    matching_items_count=len(grouped),
                    severities_present=severities,
                    source_severities_present=sorted(
                        {
                            severity
                            for item in grouped
                            for severity in [item.source_severity or item.severity]
                            if severity
                        }
                    ),
                    automation_status=status,
                    reason=reason,
                )
            )
        return inventory

    def _group_status(
        self,
        items: list[DashboardItem],
    ) -> tuple[DashboardAutomationStatus, str | None]:
        matching_exclusion = next(
            (item for item in items if self.exclusion_service.matches_dashboard_item(item)),
            None,
        )
        if matching_exclusion is not None:
            issue_key = self._issue_key_for_item(matching_exclusion)
            exclusion = next(
                (
                    exclusion
                    for exclusion in self.exclusion_service.list_exclusions()
                    if exclusion.source == matching_exclusion.source
                    and exclusion.issue_key == issue_key
                ),
                None,
            )
            reason = exclusion.reason if exclusion is not None else None
            return "excluded from automation", reason

        if self._all_items_blocked_by_severity(items):
            severities = sorted(
                {
                    severity
                    for item in items
                    for severity in [self._automation_severity_for_item(item)]
                    if severity is not None
                }
            )
            severity_text = ", ".join(severities) if severities else "unknown"
            return (
                "blocked by severity policy",
                f"Current severity policy disables {severity_text}.",
            )

        selector_reasons = [self.selector.skip_reason(item, self.state) for item in items]
        if any(reason is None for reason in selector_reasons):
            return "eligible for automation", None
        non_null_reasons = [reason for reason in selector_reasons if reason is not None]
        if non_null_reasons and all(reason in _SAFETY_SKIP_REASONS for reason in non_null_reasons):
            return (
                "blocked by safety guard",
                "Current items are outside the remediation safety boundary.",
            )
        return "eligible for automation", None

    def _all_items_blocked_by_severity(self, items: list[DashboardItem]) -> bool:
        enabled = {severity.lower() for severity in self.config.remediation.supported_severities}
        severities = [
            severity
            for item in items
            for severity in [self._automation_severity_for_item(item)]
            if severity is not None
        ]
        if not severities:
            return False
        return all(severity not in enabled for severity in severities)

    def _issue_key_for_item(self, item: DashboardItem) -> str | None:
        if item.source == "sonarqube":
            return item.rule
        return None

    def _automation_severity_for_item(self, item: DashboardItem) -> str | None:
        if item.automation_severity:
            return item.automation_severity.lower()
        if item.severity:
            return item.severity.lower()
        return None
