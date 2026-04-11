"""Dashboard markdown parser."""

from __future__ import annotations

import json
import re

from ai_sonar_bot.models.dashboard import (
    SECTION_ORDER,
    SECTION_TITLES,
    DashboardDocument,
    DashboardItem,
    DashboardSection,
)


class DashboardParseError(RuntimeError):
    """Raised when dashboard markdown cannot be parsed safely."""


_ITEM_BLOCK_PATTERN = re.compile(
    (
        r"^<details>\n"
        r"<summary><code>(?P<item_id>[^\n<]+)</code> details</summary>\n\n"
        r"```json\n(?P<payload>.*?)\n```\n\n"
        r"</details>\n?$"
    ),
    re.MULTILINE | re.DOTALL,
)


class DashboardParser:
    """Parse deterministic dashboard markdown into structured models."""

    def parse(
        self,
        *,
        issue_id: int,
        issue_iid: int,
        issue_url: str,
        title: str,
        body: str,
    ) -> DashboardDocument:
        """Parse one dashboard issue body."""
        sections = [
            DashboardSection(key=key, title=SECTION_TITLES[key], items=[]) for key in SECTION_ORDER
        ]
        for section in sections:
            content = self._extract_section_content(body, section.title)
            section.items = self._parse_section_items(content)
        return DashboardDocument(
            issue_id=issue_id,
            issue_iid=issue_iid,
            issue_url=issue_url,
            title=title,
            sections=sections,
        )

    def _extract_section_content(self, body: str, section_title: str) -> str:
        section_heading = f"## {section_title}\n"
        start = body.find(section_heading)
        if start == -1:
            return ""
        start += len(section_heading)
        next_index = body.find("\n## ", start)
        if next_index == -1:
            return body[start:].strip()
        return body[start:next_index].strip()

    def _parse_section_items(self, content: str) -> list[DashboardItem]:
        if not content or content == "No items.":
            return []
        matches = list(_ITEM_BLOCK_PATTERN.finditer(content))
        if not matches:
            raise DashboardParseError("Dashboard section did not contain parseable item blocks.")
        parsed: list[DashboardItem] = []
        normalized_blocks: list[str] = []
        for match in matches:
            payload_text = match.group("payload")
            try:
                payload = json.loads(payload_text)
            except json.JSONDecodeError as error:
                raise DashboardParseError("Dashboard item block contained invalid JSON.") from error
            item = DashboardItem.model_validate(payload)
            if item.id != match.group("item_id"):
                raise DashboardParseError("Dashboard item heading ID did not match JSON payload.")
            parsed.append(item)
            normalized_blocks.append(match.group(0))
        remaining = content
        for block in normalized_blocks:
            remaining = remaining.replace(block, "", 1)
        if not self._is_supported_summary_content(remaining):
            raise DashboardParseError("Dashboard section contained unsupported free-form content.")
        return parsed

    def _is_supported_summary_content(self, content: str) -> bool:
        """Return whether remaining section content is a supported summary table."""
        stripped = content.strip()
        if not stripped:
            return True
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if len(lines) < 2:
            return False
        supported_headers = {
            (
                "| ID | Source | Type | File | Rule | Status | Priority |",
                "|---|---|---|---|---|---|---|",
            ),
            (
                "| ID | Source | Type | File | Rule | Status | Priority | Note |",
                "|---|---|---|---|---|---|---|---|",
            ),
        }
        if (lines[0], lines[1]) not in supported_headers:
            return False
        return all(line.startswith("| ") and line.endswith(" |") for line in lines[2:])
