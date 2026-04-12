"""Dashboard markdown renderer."""

from __future__ import annotations

import json

from ai_sonar_bot.models.dashboard import DashboardDocument, DashboardItem, DashboardSection


class DashboardRenderer:
    """Render deterministic dashboard markdown."""

    def render(self, *, title: str, sections: list[DashboardSection]) -> str:
        """Render one dashboard body."""
        lines = [
            f"# {title}",
            "",
            "Machine-managed dashboard for AI Code Ops work items.",
            "",
        ]
        for section in sections:
            lines.extend(self._render_section(section))
        return "\n".join(lines).rstrip() + "\n"

    def _render_section(self, section: DashboardSection) -> list[str]:
        lines = [f"## {section.title}", ""]
        if not section.items:
            lines.extend(["No items.", ""])
            return lines
        lines.extend(self._render_summary_table(section.items))
        lines.append("")
        for item in section.items:
            lines.extend(self._render_item(item))
            lines.append("")
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
