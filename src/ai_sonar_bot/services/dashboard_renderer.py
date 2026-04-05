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
            "| ID | Source | Type | File | Rule | Status | Priority |",
            "|---|---|---|---|---|---|---|",
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
                f"`{item.priority}` |"
            )
        return lines

    def _render_item(self, item: DashboardItem) -> list[str]:
        payload = item.model_dump(exclude_none=True)
        return [
            f"### Item: {item.id}",
            "",
            "```json",
            json.dumps(payload, indent=2, sort_keys=True),
            "```",
        ]

    def render_document(self, document: DashboardDocument) -> str:
        """Render one structured dashboard document."""
        return self.render(title=document.title, sections=document.sections)
