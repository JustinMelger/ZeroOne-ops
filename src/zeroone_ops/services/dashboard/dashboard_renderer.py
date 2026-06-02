"""Dashboard markdown renderer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from zeroone_ops.models.dashboard import (
    CURRENT_DASHBOARD_SCHEMA_VERSION,
    DASHBOARD_SCHEMA_MARKER,
    DashboardDocument,
    DashboardIssueClassExclusionEntry,
    DashboardIssueClassInventoryEntry,
    DashboardItem,
    DashboardManifest,
    DashboardPolicyState,
    DashboardPolicyView,
    DashboardSection,
    DashboardSeverityPolicyEntry,
    build_dashboard_manifest,
)

WORKFLOW_BUCKET_DISPLAY_LIMITS: dict[str, int] = {
    "queue_auto_fix": 10,
    "needs_review": 10,
    "in_flight": 10,
    "completed": 10,
    "dismissed": 10,
}


class DashboardRenderer:
    """Render deterministic dashboard markdown."""

    def render(
        self,
        *,
        title: str,
        sections: list[DashboardSection],
        schema_version: int = CURRENT_DASHBOARD_SCHEMA_VERSION,
        policy_state: DashboardPolicyState | None = None,
        policy_view: DashboardPolicyView | None = None,
    ) -> str:
        """Render one dashboard body."""
        lines = [
            (
                DASHBOARD_SCHEMA_MARKER
                if schema_version == CURRENT_DASHBOARD_SCHEMA_VERSION
                else f"<!-- zeroone-ops:dashboard-schema:v{schema_version} -->"
            ),
            "",
            "Machine-managed remediation and review items for this repository.",
            "",
        ]
        if schema_version >= 2:
            lines.extend(self._render_manifest_block(build_dashboard_manifest(sections)))
            lines.append("")
        policy_view = policy_view or DashboardPolicyView()
        lines.extend(
            self._render_policy_sections(
                policy_view,
                policy_state or DashboardPolicyState(),
            )
        )
        workflow_items = self._workflow_items(
            sections,
            policy_state=policy_state or DashboardPolicyState(),
        )
        review_projection_items = self._review_projection_items(sections)
        for section in sections:
            rendered = self._render_section(
                section,
                workflow_items=workflow_items,
                review_projection_items=review_projection_items,
            )
            if rendered:
                lines.extend(rendered)
        return "\n".join(lines).rstrip() + "\n"

    def _render_manifest_block(self, manifest: DashboardManifest) -> list[str]:
        """Render the canonical machine-managed dashboard integrity manifest."""
        payload = manifest.model_dump(mode="json", exclude_none=True)
        return [
            "<details>",
            "<summary><code>zeroone-dashboard-manifest</code> machine state</summary>",
            "",
            "```json",
            json.dumps(payload, indent=2, sort_keys=True),
            "```",
            "",
            "</details>",
        ]

    def _render_policy_sections(
        self,
        policy_view: DashboardPolicyView,
        policy_state: DashboardPolicyState,
    ) -> list[str]:
        """Render the read-only operator policy sections."""
        lines: list[str] = [
            "## Automation Severity Policy",
            "",
        ]
        lines.extend(self._render_severity_policy_table(policy_view.severity_policy))
        lines.extend(["", "## Excluded Issue Classes", ""])
        lines.extend(self._render_excluded_issue_classes_table(policy_view.excluded_issue_classes))
        lines.extend(["", "## Issue Class Inventory", ""])
        lines.extend(self._render_issue_class_inventory_table(policy_view.issue_class_inventory))
        lines.extend(["", "## Operator Policy Actions", ""])
        lines.extend(self._render_policy_state_block(policy_state))
        lines.append("")
        lines.extend(self._render_operator_policy_actions_legend())
        lines.append("")
        return lines

    def _render_policy_state_block(self, policy_state: DashboardPolicyState) -> list[str]:
        """Render the canonical machine-readable dashboard policy state block."""
        payload = policy_state.model_dump(mode="json", exclude_none=True)
        return [
            "<details>",
            "<summary><code>zeroone-policy-state</code> machine state</summary>",
            "",
            "```json",
            json.dumps(payload, indent=2, sort_keys=True),
            "```",
            "",
            "</details>",
        ]

    def _render_operator_policy_actions_legend(self) -> list[str]:
        """Render the machine-owned operator action legend."""
        return [
            "Use strict dashboard issue comments with the exact `/zeroone policy` prefix.",
            "",
            "| Action | Command |",
            "|---|---|",
            "| Enable a severity | `/zeroone policy severity enable high` |",
            "| Disable a severity | `/zeroone policy severity disable high` |",
            (
                "| Exclude an issue class | "
                "`/zeroone policy issue-class exclude sonarqube / python:S3776` |"
            ),
            (
                "| Remove an issue-class exclusion | "
                "`/zeroone policy issue-class include sonarqube / python:S3776` |"
            ),
            "",
            (
                "Direct markdown edits and raw checkbox changes in this dashboard are "
                "display-only and do not mutate operator policy."
            ),
        ]

    def _render_severity_policy_table(
        self,
        rows: list[DashboardSeverityPolicyEntry],
    ) -> list[str]:
        lines = [
            "| Severity | Automation Status | Reason |",
            "|---|---|---|",
        ]
        for row in rows:
            status = "eligible for automation" if row.enabled else "blocked by severity policy"
            lines.append(f"| `{row.severity}` | {status} | {row.reason or '-'} |")
        return lines

    def _render_excluded_issue_classes_table(
        self,
        rows: list[DashboardIssueClassExclusionEntry],
    ) -> list[str]:
        if not rows:
            return ["No items."]
        lines = [
            "| Issue Class | Automation Status | Matching Items | Reason |",
            "|---|---|---|---|",
        ]
        for row in rows:
            lines.append(
                "| "
                f"`{row.source} / {row.issue_key}` | "
                "excluded from automation | "
                f"{row.matching_items_count} | "
                f"{row.reason} |"
            )
        return lines

    def _render_issue_class_inventory_table(
        self,
        rows: list[DashboardIssueClassInventoryEntry],
    ) -> list[str]:
        if not rows:
            return ["No items."]
        lines = [
            "| Issue Class | Automation Status | Count | Severities | Reason |",
            "|---|---|---|---|---|",
        ]
        for row in rows:
            severities = ", ".join(severity.upper() for severity in row.severities_present) or "-"
            lines.append(
                "| "
                f"`{row.source} / {row.issue_key}` | "
                f"{self._render_inventory_status(row.automation_status)} | "
                f"{row.matching_items_count} | {severities} | "
                f"{row.reason or '-'} |"
            )
        return lines

    def _render_inventory_status(self, status: str) -> str:
        return status

    def _render_section(
        self,
        section: DashboardSection,
        *,
        workflow_items: list[DashboardItem],
        review_projection_items: list[DashboardItem],
    ) -> list[str]:
        if section.key in {
            "in_progress",
            "merge_requests_opened",
            "completed",
            "rejected_or_ignored",
            "recent_failures",
        }:
            return []
        lines = [f"## {section.title}", ""]
        if section.key == "open_candidates":
            workflow_lines, visible_items, hidden_items = self._render_workflow_section(
                workflow_items
            )
            lines.extend(workflow_lines)
            lines.append("")
            for item in visible_items:
                lines.extend(self._render_item(item))
                lines.append("")
            if hidden_items:
                lines.extend(self._render_hidden_workflow_items_block(hidden_items))
                lines.append("")
            return lines
        if section.key == "merge_request_reviews":
            lines.extend(self._render_merge_request_review_section(review_projection_items))
            lines.append("")
            for item in section.items:
                lines.extend(self._render_item(item))
                lines.append("")
            return lines
        if not section.items:
            lines.extend(["No items.", ""])
            return lines
        lines.extend(self._render_summary_table(section.items))
        lines.append("")
        for item in section.items:
            lines.extend(self._render_item(item))
            lines.append("")
        return lines

    def _workflow_items(
        self,
        sections: list[DashboardSection],
        *,
        policy_state: DashboardPolicyState,
    ) -> list[DashboardItem]:
        """Return all non-review workflow items in deterministic display order."""
        items = [
            item
            for section in sections
            if section.key != "merge_request_reviews"
            for item in section.items
        ]
        status_order = {
            "open": 0,
            "failed": 1,
            "in_progress": 2,
            "mr_opened": 3,
            "rejected": 4,
            "ignored": 5,
            "done": 6,
        }
        return sorted(
            items,
            key=lambda item: (
                status_order.get(item.status, 99),
                self._workflow_policy_rank(item, policy_state=policy_state),
                self._workflow_area_key(item),
                self._workflow_file_key(item),
                item.priority,
                item.id,
            ),
        )

    def _workflow_policy_rank(
        self,
        item: DashboardItem,
        *,
        policy_state: DashboardPolicyState,
    ) -> int:
        """Return one display rank that prefers policy-eligible items under bucket caps."""
        if not policy_state.severity_policy:
            return 0
        enabled = {
            entry.severity.lower() for entry in policy_state.severity_policy if entry.enabled
        }
        automation_severity = (item.automation_severity or item.severity or "").lower()
        if not automation_severity:
            return 0
        return 0 if automation_severity in enabled else 1

    def _review_projection_items(self, sections: list[DashboardSection]) -> list[DashboardItem]:
        """Return all items that should contribute to the MR review projection."""
        items = [
            item
            for section in sections
            for item in section.items
            if item.review_status is not None or item.type == "review_status"
        ]
        return sorted(
            items,
            key=lambda item: (
                self._review_sort_key(item),
                self._review_group_key(item),
                item.id,
            ),
            reverse=True,
        )

    def _render_workflow_section(
        self,
        items: list[DashboardItem],
    ) -> tuple[list[str], list[DashboardItem], list[DashboardItem]]:
        """Render the human-facing overview for remediation and reconciliation workflow items."""
        lines: list[str] = ["### Overview", ""]
        visible_items: list[DashboardItem] = []
        lines.extend(self._render_workflow_overview_table(items))
        lines.extend(["", "### Queue Auto-fix", ""])
        queue_items = [item for item in items if item.status == "open"]
        if queue_items:
            limit = self._bucket_limit("queue_auto_fix")
            visible_items.extend(queue_items[:limit])
            lines.extend(
                self._render_bucket_with_overflow(
                    self._render_workflow_queue_table(queue_items[:limit]),
                    total_count=len(queue_items),
                    visible_count=min(len(queue_items), limit),
                )
            )
        else:
            lines.append("No items.")
        lines.extend(["", "### Needs Review", ""])
        review_items = [item for item in items if item.status == "failed"]
        if review_items:
            limit = self._bucket_limit("needs_review")
            visible_items.extend(review_items[:limit])
            lines.extend(
                self._render_bucket_with_overflow(
                    self._render_workflow_review_table(review_items[:limit]),
                    total_count=len(review_items),
                    visible_count=min(len(review_items), limit),
                )
            )
        else:
            lines.append("No items.")
        lines.extend(["", "### In Flight", ""])
        in_flight_items = [item for item in items if item.status in {"in_progress", "mr_opened"}]
        if in_flight_items:
            limit = self._bucket_limit("in_flight")
            visible_items.extend(in_flight_items[:limit])
            lines.extend(
                self._render_bucket_with_overflow(
                    self._render_in_flight_table(in_flight_items[:limit]),
                    total_count=len(in_flight_items),
                    visible_count=min(len(in_flight_items), limit),
                )
            )
        else:
            lines.append("No items.")
        lines.extend(["", "### Completed", ""])
        completed_items = [item for item in items if item.status == "done"]
        if completed_items:
            limit = self._bucket_limit("completed")
            visible_items.extend(completed_items[:limit])
            lines.extend(
                self._render_bucket_with_overflow(
                    self._render_completed_table(completed_items[:limit]),
                    total_count=len(completed_items),
                    visible_count=min(len(completed_items), limit),
                )
            )
        else:
            lines.append("No items.")
        lines.extend(["", "### Dismissed", ""])
        dismissed_items = [item for item in items if item.status in {"rejected", "ignored"}]
        if dismissed_items:
            limit = self._bucket_limit("dismissed")
            visible_items.extend(dismissed_items[:limit])
            lines.extend(
                self._render_bucket_with_overflow(
                    self._render_dismissed_table(dismissed_items[:limit]),
                    total_count=len(dismissed_items),
                    visible_count=min(len(dismissed_items), limit),
                )
            )
        else:
            lines.append("No items.")
        lines.extend(["", "### Work Type Breakdown", ""])
        lines.extend(self._render_work_type_breakdown_table(items))
        visible_ids = {item.id for item in visible_items}
        hidden_items = [item for item in items if item.id not in visible_ids]
        return lines, visible_items, hidden_items

    def _render_workflow_overview_table(self, items: list[DashboardItem]) -> list[str]:
        """Render one compact metrics table for workflow items."""
        open_count = sum(1 for item in items if item.status == "open")
        in_progress_count = sum(1 for item in items if item.status == "in_progress")
        mr_opened_count = sum(1 for item in items if item.status == "mr_opened")
        failed_count = sum(1 for item in items if item.status == "failed")
        done_count = sum(1 for item in items if item.status == "done")
        return [
            "| Open | In progress | MR opened | Failed | Done |",
            "|---|---|---|---|---|",
            (
                f"| {open_count} | {in_progress_count} | {mr_opened_count} | "
                f"{failed_count} | {done_count} |"
            ),
        ]

    def _render_workflow_queue_table(self, items: list[DashboardItem]) -> list[str]:
        """Render the focused queue of workflow items ready for automation."""
        lines = [
            "| Item | Area | File | Priority | Next Step | Summary |",
            "|---|---|---|---|---|---|",
        ]
        for item in items:
            lines.append(
                "| "
                f"{self._render_workflow_item_label(item)} | "
                f"{self._render_workflow_area(item)} | "
                f"{self._render_workflow_file(item)} | "
                f"{self._render_priority(item)} | "
                f"{self._render_suggested_action(item)} | "
                f"{self._render_workflow_summary(item)} |"
            )
        return lines

    def _render_workflow_review_table(self, items: list[DashboardItem]) -> list[str]:
        """Render workflow items that currently need human review or investigation."""
        lines = [
            "| Item | Area | File | Priority | Next Step | Summary |",
            "|---|---|---|---|---|---|",
        ]
        for item in items:
            lines.append(
                "| "
                f"{self._render_workflow_item_label(item)} | "
                f"{self._render_workflow_area(item)} | "
                f"{self._render_workflow_file(item)} | "
                f"{self._render_priority(item)} | "
                f"{self._render_suggested_action(item)} | "
                f"{self._render_workflow_summary(item)} |"
            )
        return lines

    def _render_in_flight_table(self, items: list[DashboardItem]) -> list[str]:
        """Render the in-flight workflow queue."""
        lines = [
            "| Item | Area | Status | Priority | Review Summary |",
            "|---|---|---|---|---|",
        ]
        for item in items:
            lines.append(
                "| "
                f"{self._render_workflow_item_label(item)} | "
                f"{self._render_workflow_area(item)} | "
                f"{self._render_workflow_status(item)} | "
                f"{self._render_priority(item)} | "
                f"{self._render_in_flight_summary(item)} |"
            )
        return lines

    def _render_completed_table(self, items: list[DashboardItem]) -> list[str]:
        """Render the completed workflow queue."""
        lines = [
            "| Item | Area | Priority | Summary |",
            "|---|---|---|---|",
        ]
        for item in items:
            lines.append(
                "| "
                f"{self._render_workflow_item_label(item)} | "
                f"{self._render_workflow_area(item)} | "
                f"{self._render_priority(item)} | "
                f"{self._render_completed_summary(item)} |"
            )
        return lines

    def _render_dismissed_table(self, items: list[DashboardItem]) -> list[str]:
        """Render dismissed or intentionally excluded workflow items."""
        lines = [
            "| Item | Area | Status | Priority | Summary |",
            "|---|---|---|---|---|",
        ]
        for item in items:
            lines.append(
                "| "
                f"{self._render_workflow_item_label(item)} | "
                f"{self._render_workflow_area(item)} | "
                f"{self._render_workflow_status(item)} | "
                f"{self._render_priority(item)} | "
                f"{self._render_completed_summary(item)} |"
            )
        return lines

    def _render_work_type_breakdown_table(self, items: list[DashboardItem]) -> list[str]:
        """Render a compact breakdown of repeated work patterns."""
        workflow_items = [item for item in items if item.type != "review_status"]
        if not workflow_items:
            return ["No items."]

        counts: dict[str, int] = {}
        for item in workflow_items:
            label = self._work_type_label(item)
            counts[label] = counts.get(label, 0) + 1

        sorted_counts = sorted(counts.items(), key=lambda entry: (-entry[1], entry[0].lower()))
        lines = [
            "| Work Type | Count |",
            "|---|---|",
        ]
        for label, count in sorted_counts[:8]:
            lines.append(f"| {label} | {count} |")
        return lines

    def _bucket_limit(self, bucket_key: str) -> int:
        """Return the visible display limit for one workflow bucket."""
        return WORKFLOW_BUCKET_DISPLAY_LIMITS[bucket_key]

    def _render_bucket_with_overflow(
        self,
        rendered_lines: list[str],
        *,
        total_count: int,
        visible_count: int,
    ) -> list[str]:
        """Render one bucket table plus an explicit overflow note when needed."""
        lines = list(rendered_lines)
        hidden_count = total_count - visible_count
        if hidden_count > 0:
            lines.append(f"_{hidden_count} more items not shown._")
        return lines

    def _render_hidden_workflow_items_block(self, items: list[DashboardItem]) -> list[str]:
        """Render compact machine state for workflow items hidden by summary caps."""
        payload = [item.model_dump(mode="json", exclude_none=True) for item in items]
        return [
            "<details>",
            "<summary><code>zeroone-workflow-hidden-items</code> machine state</summary>",
            "",
            "```json",
            json.dumps(payload, indent=2, sort_keys=True),
            "```",
            "",
            "</details>",
        ]

    def _render_merge_request_review_section(self, items: list[DashboardItem]) -> list[str]:
        """Render the human-facing review overview for merge request reviews."""
        groups = self._group_review_items(items)
        lines: list[str] = ["### Overview", ""]
        lines.extend(self._render_review_overview_table(groups))
        lines.extend(["", "### Needs Attention", ""])
        attention_groups = [group for group in groups if self._needs_attention(group.latest_item)]
        if attention_groups:
            lines.extend(self._render_review_attention_table(attention_groups))
        else:
            lines.append("No items.")
        lines.extend(["", "### Review History", ""])
        lines.extend(self._render_all_reviews_table(groups))
        return lines

    def _render_review_overview_table(self, groups: list[_ReviewGroup]) -> list[str]:
        """Render one compact metrics table for merge request reviews."""
        total_reviews = len(groups)
        needs_attention = sum(1 for group in groups if self._needs_attention(group.latest_item))
        findings_total = sum(group.latest_item.review_findings_count or 0 for group in groups)
        high_priority = sum(1 for group in groups if group.latest_item.priority.lower() == "high")
        return [
            "| MRs | Needs attention | Findings total | High priority |",
            "|---|---|---|---|",
            f"| {total_reviews} | {needs_attention} | {findings_total} | {high_priority} |",
        ]

    def _render_review_attention_table(self, groups: list[_ReviewGroup]) -> list[str]:
        """Render the focused attention queue for merge request reviews."""
        lines = [
            "| MR | Passes | Outcome | Findings | Confidence | Priority | Summary | Reviewed SHA |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for group in groups:
            item = group.latest_item
            lines.append(
                "| "
                f"{self._render_merge_request_label(item)} | "
                f"{group.pass_count} | "
                f"{self._render_review_outcome(item)} | "
                f"{item.review_findings_count or 0} | "
                f"{self._render_review_confidence(item)} | "
                f"{self._render_priority(item)} | "
                f"{self._render_grouped_review_summary(group)} | "
                f"`{self._short_sha(item.reviewed_head_sha)}` |"
            )
        return lines

    def _render_all_reviews_table(self, groups: list[_ReviewGroup]) -> list[str]:
        """Render grouped merge-request review history."""
        lines = [
            "| MR | Passes | Outcome | Findings | Confidence | Priority | Summary | Reviewed SHA |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for group in groups:
            item = group.latest_item
            lines.append(
                "| "
                f"{self._render_merge_request_label(item)} | "
                f"{group.pass_count} | "
                f"{self._render_review_outcome(item)} | "
                f"{item.review_findings_count or 0} | "
                f"{self._render_review_confidence(item)} | "
                f"{self._render_priority(item)} | "
                f"{self._render_grouped_review_summary(group)} | "
                f"`{self._short_sha(item.reviewed_head_sha)}` |"
            )
        return lines

    def _render_review_confidence(self, item: DashboardItem) -> str:
        """Render one compact numeric confidence value for review rows."""
        if item.review_confidence is None:
            return "-"
        return f"{item.review_confidence:.2f}"

    def _render_summary_table(self, items: list[DashboardItem]) -> list[str]:
        """Render one human-readable summary table for section items."""
        lines = [
            "| ID | Source | Type | File | Rule | Status | Priority | Note |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for item in items:
            lines.append(
                "| "
                f"`{item.id}` | "
                f"{item.source} | "
                f"{item.type} | "
                f"`{item.file or '-'}` | "
                f"`{item.rule or '-'}` | "
                f"`{item.status}` | "
                f"`{item.priority}` | "
                f"{self._render_summary_note(item)} |"
            )
        return lines

    def _render_summary_note(self, item: DashboardItem) -> str:
        """Render one compact operator note for the summary table."""
        note = self._render_review_note(item)
        if note is None:
            note = item.log_excerpt if item.status in {"failed", "rejected", "done"} else None
        if not note:
            return "-"
        return self._compact_note(note)

    def _render_review_note(self, item: DashboardItem) -> str | None:
        """Render one compact review-state note when review metadata exists."""
        if item.review_status is None:
            return None
        parts = [f"review: {item.review_status}"]
        if item.review_findings_count is not None:
            parts.append(f"findings: {item.review_findings_count}")
        if item.reviewed_head_sha:
            parts.append(f"sha: {item.reviewed_head_sha[:8]}")
        if item.retry_eligible is True:
            parts.append("retry: eligible")
        elif item.retry_block_reason:
            parts.append(f"retry: blocked ({item.retry_block_reason})")
        if item.review_feedback_summary:
            parts.append(item.review_feedback_summary)
        return "; ".join(parts)

    def _compact_note(self, note: str) -> str:
        """Normalize and bound one summary-note string."""
        compact_note = " ".join(note.split())
        if len(compact_note) > 96:
            compact_note = compact_note[:93].rstrip() + "..."
        return compact_note.replace("|", "/")

    def _render_merge_request_label(self, item: DashboardItem) -> str:
        """Render one merge request label for the review summary tables."""
        if item.merge_request_iid is not None:
            label = f"!{item.merge_request_iid}"
            if item.merge_request_url:
                return f"[{label}]({item.merge_request_url})"
            return label
        return f"`{item.id}`"

    def _render_review_outcome(self, item: DashboardItem) -> str:
        """Render one human-readable review outcome label."""
        mapping = {
            "findings_present": "Findings present",
            "no_findings": "No findings",
            "manual_review_only": "Manual review only",
        }
        if item.review_status is not None:
            label = mapping.get(item.review_status, item.review_status.replace("_", " "))
            return f"{self._review_outcome_marker(item.review_status)} {label}"
        label = item.status.replace("_", " ").title()
        return f"{self._status_marker(item.status)} {label}"

    def _render_priority(self, item: DashboardItem) -> str:
        """Render one human-readable priority label."""
        label = item.priority.replace("_", " ").title()
        return f"{self._priority_marker(item.priority)} {label}"

    def _render_review_summary(self, item: DashboardItem) -> str:
        """Render one compact human-facing summary for merge request reviews."""
        note = item.review_feedback_summary or item.summary
        return self._compact_note(note)

    def _render_grouped_review_summary(self, group: _ReviewGroup) -> str:
        """Render one grouped summary line for repeated merge-request reviews."""
        item = group.latest_item
        note = item.review_feedback_summary or item.summary
        prefix = f"{group.pass_count} passes. " if group.pass_count > 1 else ""
        return self._compact_note(f"{prefix}{note}")

    def _short_sha(self, sha: str | None) -> str:
        """Render one short SHA or placeholder."""
        if not sha:
            return "-"
        return sha[:8]

    def _render_workflow_item_label(self, item: DashboardItem) -> str:
        """Render one compact workflow item label."""
        return f"`{item.id}`"

    def _render_workflow_status(self, item: DashboardItem) -> str:
        """Render one human-readable workflow status label."""
        return f"{self._status_marker(item.status)} {item.status.replace('_', ' ').title()}"

    def _render_workflow_summary(self, item: DashboardItem) -> str:
        """Render one compact workflow summary."""
        review_note = self._render_review_note(item)
        if review_note is not None:
            return self._compact_note(review_note)
        note = (
            item.log_excerpt
            if item.status in {"failed", "rejected"} and item.log_excerpt
            else item.summary
        )
        if item.status == "failed":
            return self._render_failure_recovery_summary(item, note)
        return self._humanize_workflow_summary(item, note)

    def _render_failure_recovery_summary(self, item: DashboardItem, note: str | None) -> str:
        """Render one recovery-oriented summary for failed workflow items."""
        parts: list[str] = []
        if item.retry_eligible is True:
            parts.append("Retry ready after fixing the blocker.")
        elif item.retry_block_reason:
            parts.append(f"Blocked until review or policy changes: {item.retry_block_reason}")
        elif self._looks_operational_failure(note):
            parts.append("Investigate environment or tooling failure before rerun.")
        else:
            parts.append("Investigate failure and decide the next recovery path.")
        if note:
            parts.append(note)
        return self._compact_note(" ".join(parts))

    def _looks_operational_failure(self, note: str | None) -> bool:
        """Return whether one note looks like an environment or tooling failure."""
        if not note:
            return False
        lower = note.lower()
        markers = (
            "token",
            "credential",
            "gitlab",
            "inaccessible",
            "timeout",
            "timed out",
            "not available",
            "not executable",
            "command could not run",
            "environment",
            "tool",
        )
        return any(marker in lower for marker in markers)

    def _render_in_flight_summary(self, item: DashboardItem) -> str:
        """Render one compact in-flight summary."""
        if item.review_status is not None:
            return self._render_review_outcome(item)
        if item.merge_request_iid is not None and item.merge_request_url:
            return f"[View MR]({item.merge_request_url})"
        return self._render_workflow_summary(item)

    def _render_completed_summary(self, item: DashboardItem) -> str:
        """Render one compact completed summary."""
        if item.review_status is not None:
            return self._render_review_outcome(item)
        note = item.log_excerpt or item.summary
        return self._compact_note(note)

    def _render_workflow_file(self, item: DashboardItem) -> str:
        """Render one short file label for workflow tables."""
        if not item.file:
            return "-"
        return f"`{item.file.rsplit('/', maxsplit=1)[-1]}`"

    def _render_workflow_area(self, item: DashboardItem) -> str:
        """Render one compact area label derived from the item's file path."""
        return f"`{self._workflow_area_key(item)}`"

    def _render_suggested_action(self, item: DashboardItem) -> str:
        """Render one compact suggested-action label."""
        return self._next_step(item)

    def _workflow_area_key(self, item: DashboardItem) -> str:
        """Return one deterministic area key for scanability and grouping."""
        if not item.file:
            return "-"
        parts = [part for part in item.file.split("/") if part]
        if len(parts) <= 1:
            return parts[0] if parts else "-"
        if len(parts) == 2:
            return parts[0]
        return "/".join(parts[:2])

    def _workflow_file_key(self, item: DashboardItem) -> str:
        """Return one deterministic file key for workflow ordering."""
        return item.file or ""

    def _work_type_label(self, item: DashboardItem) -> str:
        """Render one compact grouping label for workflow breakdowns."""
        source_text = self._humanize_workflow_summary(
            item,
            item.title.strip() or item.summary.strip(),
        )
        if not source_text:
            return item.type.replace("_", " ").title()
        return self._compact_note(source_text.rstrip("."))

    def _humanize_workflow_summary(self, item: DashboardItem, note: str | None) -> str:
        """Render one shorter human-facing workflow summary."""
        if not note:
            return "-"
        text = note.strip()
        lower = text.lower()

        if "commented-out code" in lower:
            return "Remove dead commented code"
        if "nested if" in lower:
            return "Merge nested if statement"
        if "sort_order" in lower and "lambda" in lower:
            return "Capture sort_order safely in lambda"
        if "lambda" in lower and "default value" in lower:
            return "Bind value safely in lambda default"
        if "type annotation" in lower or "return type" in lower:
            return "Fix type annotation mismatch"
        if "fixture" in lower and "type" in lower:
            return "Fix fixture type annotation"
        if "unused variable" in lower:
            return "Remove unused variable"

        title = item.title.strip()
        if title:
            text = title
        return self._compact_note(text.rstrip("."))

    def _next_step(self, item: DashboardItem) -> str:
        """Return one operator-facing next step from workflow state, not summary text.

        For the current dashboard-backed Sonar remediation flow, open items on the
        board are already considered queueable auto-fix candidates. Failed items
        are the exception and need operator investigation.
        """
        if item.status == "failed":
            if item.retry_eligible is True:
                return "Retry Auto-fix"
            if item.retry_block_reason:
                return "Review Retry Blocker"
            return "Investigate Failure"
        if item.status == "rejected":
            lower_note = (item.log_excerpt or item.summary).lower()
            if "manual review" in lower_note:
                return "Review Manually"
            return "Review Rejection"
        return "Queue Auto-fix"

    def _needs_attention(self, item: DashboardItem) -> bool:
        """Return whether one review item should appear in the attention queue."""
        return item.review_status in {"findings_present", "manual_review_only"}

    def _group_review_items(self, items: list[DashboardItem]) -> list[_ReviewGroup]:
        """Group repeated review items by merge request and keep the latest pass primary."""
        grouped: dict[str, list[DashboardItem]] = {}
        for item in items:
            grouped.setdefault(self._review_group_key(item), []).append(item)
        groups = [self._build_review_group(group_items) for group_items in grouped.values()]
        return sorted(
            groups,
            key=lambda group: (
                self._review_sort_key(group.latest_item),
                self._review_group_key(group.latest_item),
            ),
            reverse=True,
        )

    def _review_group_key(self, item: DashboardItem) -> str:
        """Return the grouping key for merge-request review items."""
        if item.merge_request_url:
            return item.merge_request_url
        if item.merge_request_iid is not None:
            return f"mr:{item.merge_request_iid}"
        return item.source_reference

    def _build_review_group(self, items: list[DashboardItem]) -> _ReviewGroup:
        """Build one grouped review projection from repeated passes."""
        latest_item = max(items, key=self._review_sort_key)
        return _ReviewGroup(latest_item=latest_item, pass_count=len(items))

    def _review_sort_key(
        self,
        item: DashboardItem,
    ) -> tuple[int, datetime, int, datetime, str, str]:
        """Return one deterministic sort key for review projection recency."""
        min_datetime = datetime.min.replace(tzinfo=UTC)
        return (
            1 if item.review_feedback_updated_at is not None else 0,
            item.review_feedback_updated_at or min_datetime,
            1 if item.status_updated_at is not None else 0,
            item.status_updated_at or min_datetime,
            item.reviewed_head_sha or "",
            item.id,
        )

    def _status_marker(self, status: str) -> str:
        """Return one lightweight marker for a workflow status."""
        markers = {
            "open": "🔵",
            "in_progress": "🟠",
            "mr_opened": "📦",
            "failed": "🔴",
            "done": "✅",
            "rejected": "⚪",
            "ignored": "⚪",
        }
        return markers.get(status, "•")

    def _review_outcome_marker(self, outcome: str) -> str:
        """Return one lightweight marker for a review outcome."""
        markers = {
            "findings_present": "⚠️",
            "manual_review_only": "👀",
            "no_findings": "✅",
        }
        return markers.get(outcome, "•")

    def _priority_marker(self, priority: str) -> str:
        """Return one lightweight marker for a priority."""
        markers = {
            "high": "🔴",
            "medium": "🟡",
            "low": "🟢",
        }
        return markers.get(priority, "•")

    def _render_item(self, item: DashboardItem) -> list[str]:
        payload = item.model_dump(mode="json", exclude_none=True)
        return [
            "<details>",
            f"<summary><code>{item.id}</code> details</summary>",
            "",
            "```json",
            json.dumps(payload, indent=2, sort_keys=True),
            "```",
            "",
            "</details>",
        ]

    def render_document(self, document: DashboardDocument) -> str:
        """Render one structured dashboard document."""
        return self.render(
            title=document.title,
            sections=document.sections,
            schema_version=document.schema_version,
            policy_state=document.policy_state,
            policy_view=document.policy_view,
        )


@dataclass(frozen=True)
class _ReviewGroup:
    """Represent one grouped review-history row for a merge request."""

    latest_item: DashboardItem
    pass_count: int
