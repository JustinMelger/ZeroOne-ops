"""Dashboard markdown renderer."""

from __future__ import annotations

import json

from ai_sonar_bot.models.dashboard import DashboardDocument, DashboardItem, DashboardSection


class DashboardRenderer:
    """Render deterministic dashboard markdown."""

    def render(self, *, title: str, sections: list[DashboardSection]) -> str:
        """Render one dashboard body."""
        lines = [
            "Machine-managed dashboard for AI Code Ops work items.",
            "",
        ]
        workflow_items = self._workflow_items(sections)
        for section in sections:
            rendered = self._render_section(section, workflow_items=workflow_items)
            if rendered:
                lines.extend(rendered)
        return "\n".join(lines).rstrip() + "\n"

    def _render_section(
        self,
        section: DashboardSection,
        *,
        workflow_items: list[DashboardItem],
    ) -> list[str]:
        if section.key in {
            "in_progress",
            "merge_requests_opened",
            "completed",
            "rejected_or_ignored",
            "recent_failures",
        } and workflow_items:
            return []
        lines = [f"## {section.title}", ""]
        if section.key == "open_candidates":
            if not workflow_items:
                lines.extend(["No items.", ""])
                return lines
            lines.extend(self._render_workflow_section(workflow_items))
            lines.append("")
            for item in workflow_items:
                lines.extend(self._render_item(item))
                lines.append("")
            return lines
        if not section.items:
            lines.extend(["No items.", ""])
            return lines
        if section.key == "merge_request_reviews":
            lines.extend(self._render_merge_request_review_section(section.items))
            lines.append("")
            for item in section.items:
                lines.extend(self._render_item(item))
                lines.append("")
            return lines
        lines.extend(self._render_summary_table(section.items))
        lines.append("")
        for item in section.items:
            lines.extend(self._render_item(item))
            lines.append("")
        return lines

    def _workflow_items(self, sections: list[DashboardSection]) -> list[DashboardItem]:
        """Return all non-review workflow items in deterministic display order."""
        items = [
            item
            for section in sections
            if section.key != "merge_request_reviews"
            for item in section.items
        ]
        status_order = {
            "failed": 0,
            "open": 1,
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
                item.priority,
                item.id,
            ),
        )

    def _render_workflow_section(self, items: list[DashboardItem]) -> list[str]:
        """Render the human-facing overview for remediation and reconciliation workflow items."""
        lines: list[str] = ["### Overview", ""]
        lines.extend(self._render_workflow_overview_table(items))
        lines.extend(["", "### Needs Attention", ""])
        attention_items = [item for item in items if self._workflow_needs_attention(item)]
        if attention_items:
            lines.extend(self._render_workflow_attention_table(attention_items))
        else:
            lines.append("No items.")
        lines.extend(["", "### All Workflow Items", ""])
        lines.extend(self._render_all_workflow_items_table(items))
        return lines

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

    def _render_workflow_attention_table(self, items: list[DashboardItem]) -> list[str]:
        """Render the focused queue of workflow items that need operator attention."""
        lines = [
            "| Item | Status | Priority | Summary |",
            "|---|---|---|---|",
        ]
        for item in items:
            lines.append(
                "| "
                f"{self._render_workflow_item_label(item)} | "
                f"{self._render_workflow_status(item)} | "
                f"{self._render_priority(item)} | "
                f"{self._render_workflow_summary(item)} |"
            )
        return lines

    def _render_all_workflow_items_table(self, items: list[DashboardItem]) -> list[str]:
        """Render the full remediation and reconciliation workflow table."""
        lines = [
            "| Item | Status | Priority | Summary |",
            "|---|---|---|---|",
        ]
        for item in items:
            lines.append(
                "| "
                f"{self._render_workflow_item_label(item)} | "
                f"{self._render_workflow_status(item)} | "
                f"{self._render_priority(item)} | "
                f"{self._render_workflow_summary(item)} |"
            )
        return lines

    def _render_merge_request_review_section(self, items: list[DashboardItem]) -> list[str]:
        """Render the human-facing review overview for merge request reviews."""
        lines: list[str] = ["### Overview", ""]
        lines.extend(self._render_review_overview_table(items))
        lines.extend(["", "### Needs Attention", ""])
        attention_items = [item for item in items if self._needs_attention(item)]
        if attention_items:
            lines.extend(self._render_review_attention_table(attention_items))
        else:
            lines.append("No items.")
        lines.extend(["", "### All Reviews", ""])
        lines.extend(self._render_all_reviews_table(items))
        return lines

    def _render_review_overview_table(self, items: list[DashboardItem]) -> list[str]:
        """Render one compact metrics table for merge request reviews."""
        total_reviews = len(items)
        needs_attention = sum(1 for item in items if self._needs_attention(item))
        findings_total = sum(item.review_findings_count or 0 for item in items)
        high_priority = sum(1 for item in items if item.priority.lower() == "high")
        return [
            "| Reviews | Needs attention | Findings total | High priority |",
            "|---|---|---|---|",
            f"| {total_reviews} | {needs_attention} | {findings_total} | {high_priority} |",
        ]

    def _render_review_attention_table(self, items: list[DashboardItem]) -> list[str]:
        """Render the focused attention queue for merge request reviews."""
        lines = [
            "| MR | Outcome | Findings | Priority | Summary |",
            "|---|---|---|---|---|",
        ]
        for item in items:
            lines.append(
                "| "
                f"{self._render_merge_request_label(item)} | "
                f"{self._render_review_outcome(item)} | "
                f"{item.review_findings_count or 0} | "
                f"{self._render_priority(item)} | "
                f"{self._render_review_summary(item)} |"
            )
        return lines

    def _render_all_reviews_table(self, items: list[DashboardItem]) -> list[str]:
        """Render the full merge request review history table."""
        lines = [
            "| MR | Outcome | Findings | Priority | Summary | Reviewed SHA |",
            "|---|---|---|---|---|---|",
        ]
        for item in items:
            lines.append(
                "| "
                f"{self._render_merge_request_label(item)} | "
                f"{self._render_review_outcome(item)} | "
                f"{item.review_findings_count or 0} | "
                f"{self._render_priority(item)} | "
                f"{self._render_review_summary(item)} | "
                f"`{self._short_sha(item.reviewed_head_sha)}` |"
            )
        return lines

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

    def _short_sha(self, sha: str | None) -> str:
        """Render one short SHA or placeholder."""
        if not sha:
            return "-"
        return sha[:8]

    def _render_workflow_item_label(self, item: DashboardItem) -> str:
        """Render one compact workflow item label."""
        if item.merge_request_iid is not None and item.merge_request_url:
            return f"[!{item.merge_request_iid}]({item.merge_request_url})"
        if item.file:
            return f"`{item.id}` ({item.file})"
        return f"`{item.id}`"

    def _render_workflow_status(self, item: DashboardItem) -> str:
        """Render one human-readable workflow status label."""
        return f"{self._status_marker(item.status)} {item.status.replace('_', ' ').title()}"

    def _render_workflow_summary(self, item: DashboardItem) -> str:
        """Render one compact workflow summary."""
        review_note = self._render_review_note(item)
        if review_note is not None:
            return self._compact_note(review_note)
        note = item.log_excerpt if item.status == "failed" and item.log_excerpt else item.summary
        return self._compact_note(note)

    def _workflow_needs_attention(self, item: DashboardItem) -> bool:
        """Return whether one workflow item should appear in the attention queue."""
        return item.status in {"open", "in_progress", "mr_opened", "failed"}

    def _needs_attention(self, item: DashboardItem) -> bool:
        """Return whether one review item should appear in the attention queue."""
        return item.review_status in {"findings_present", "manual_review_only"}

    def _status_marker(self, status: str) -> str:
        """Return one lightweight marker for a workflow status."""
        markers = {
            "open": "🟡",
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
        return self.render(title=document.title, sections=document.sections)
