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
    DashboardPolicyState,
    DashboardPolicyView,
)
from zeroone_ops.models.state import AppState
from zeroone_ops.services.control_plane.policy.policy_view_builder import PolicyViewBuilder
from zeroone_ops.services.dashboard.dashboard_item_selector import DashboardItemSelector

_SEVERITY_ORDER: tuple[Literal["low", "medium", "high"], ...] = ("low", "medium", "high")
_TOP_ACTIVE_GROUP_LIMIT = 5
_SAFETY_SKIP_REASONS = frozenset(
    {
        "missing_file_path",
        "missing_local_file",
        "retry_blocked",
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
        self.policy_view_builder = PolicyViewBuilder(
            bootstrap_severities=config.remediation.bootstrap_severities
        )

    def resolve_policy_state(
        self,
        policy_state: DashboardPolicyState | None,
    ) -> DashboardPolicyState:
        """Return the canonical policy state with config-seeded severity defaults."""
        return self.policy_view_builder.resolve_policy_state(policy_state)

    def build(
        self,
        items: list[DashboardItem],
        *,
        policy_state: DashboardPolicyState | None = None,
    ) -> DashboardPolicyView:
        """Return the rendered read-only policy view for current dashboard items."""
        resolved_policy_state = self.resolve_policy_state(policy_state)
        compact_view = self.policy_view_builder.build(policy_state=resolved_policy_state)
        return DashboardPolicyView(
            severity_policy=compact_view.severity_policy,
            excluded_issue_classes=self._build_excluded_issue_classes(
                items,
                rows=compact_view.excluded_issue_classes,
            ),
            issue_class_inventory=self._build_issue_class_inventory(
                items,
                policy_state=resolved_policy_state,
            ),
        )

    def _build_excluded_issue_classes(
        self,
        items: list[DashboardItem],
        *,
        rows: list[DashboardIssueClassExclusionEntry],
    ) -> list[DashboardIssueClassExclusionEntry]:
        return [
            row.model_copy(
                update={
                    "matching_items_count": sum(
                        1
                        for item in items
                        if item.source == row.source
                        and self._issue_key_for_item(item) == row.issue_key
                    )
                }
            )
            for row in rows
        ]

    def _build_issue_class_inventory(
        self,
        items: list[DashboardItem],
        *,
        policy_state: DashboardPolicyState,
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
            for exclusion in policy_state.issue_class_exclusions
        }
        blocked_severity_keys = {
            key
            for key, grouped in grouped_items.items()
            if self._all_items_blocked_by_severity(grouped, policy_state=policy_state)
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
            status, reason = self._group_status(grouped, policy_state=policy_state)
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
        *,
        policy_state: DashboardPolicyState,
    ) -> tuple[DashboardAutomationStatus, str | None]:
        exclusion = next(
            (
                exclusion
                for exclusion in policy_state.issue_class_exclusions
                if any(
                    exclusion.source == item.source
                    and exclusion.issue_key == self._issue_key_for_item(item)
                    for item in items
                )
            ),
            None,
        )
        if exclusion is not None:
            return "excluded from automation", exclusion.reason

        if self._all_items_blocked_by_severity(items, policy_state=policy_state):
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

    def _all_items_blocked_by_severity(
        self,
        items: list[DashboardItem],
        *,
        policy_state: DashboardPolicyState,
    ) -> bool:
        enabled = {
            entry.severity.lower() for entry in policy_state.severity_policy if entry.enabled
        }
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
        return item.rule

    def _automation_severity_for_item(self, item: DashboardItem) -> str | None:
        if item.automation_severity:
            return item.automation_severity.lower()
        if item.severity:
            return item.severity.lower()
        return None
