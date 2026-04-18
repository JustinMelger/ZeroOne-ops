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
    section_key_for_item,
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
            section.items = self._parse_section_items(section.key, content)
        sections = self._redistribute_workflow_items(sections)
        return DashboardDocument(
            issue_id=issue_id,
            issue_iid=issue_iid,
            issue_url=issue_url,
            title=title,
            sections=sections,
        )

    def _extract_section_content(self, body: str, section_title: str) -> str:
        pattern = re.compile(
            rf"^## {re.escape(section_title)}\n(?P<content>.*?)(?=^## |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(body)
        if match is None:
            return ""
        return match.group("content").strip()

    def _parse_section_items(self, section_key: str, content: str) -> list[DashboardItem]:
        if not content or content == "No items.":
            return []
        matches = list(_ITEM_BLOCK_PATTERN.finditer(content))
        if not matches:
            if self._is_supported_summary_content(section_key, content):
                return []
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
        if not self._is_supported_summary_content(section_key, remaining):
            raise DashboardParseError("Dashboard section contained unsupported free-form content.")
        return parsed

    def _is_supported_summary_content(self, section_key: str, content: str) -> bool:
        """Return whether remaining section content is a supported summary table."""
        stripped = content.strip()
        if not stripped:
            return True
        if section_key == "merge_request_reviews":
            return self._is_supported_review_summary_content(stripped)
        if section_key == "open_candidates":
            return self._is_supported_workflow_summary_content(stripped)
        return self._is_supported_generic_summary_content(stripped)

    def _is_supported_generic_summary_content(self, content: str) -> bool:
        """Return whether remaining content is a supported generic summary table."""
        lines = [line.strip() for line in content.splitlines() if line.strip()]
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

    def _is_supported_review_summary_content(self, content: str) -> bool:
        """Return whether remaining content is a supported review summary layout."""
        blocks = self._summary_blocks(content)
        if len(blocks) != 6:
            return False
        if blocks[0] != ["### Overview"]:
            return False
        if not self._matches_table(
            blocks[1],
            header="| Reviews | Needs attention | Findings total | High priority |",
            separator="|---|---|---|---|",
        ):
            return False
        if blocks[2] != ["### Needs Attention"]:
            return False
        if blocks[3] != ["No items."] and not self._matches_table(
            blocks[3],
            header="| MR | Outcome | Findings | Confidence | Priority | Summary |",
            separator="|---|---|---|---|---|---|",
        ):
            return False
        if blocks[4] != ["### All Reviews"]:
            return False
        return self._matches_table(
            blocks[5],
            header="| MR | Outcome | Findings | Confidence | Priority | Summary | Reviewed SHA |",
            separator="|---|---|---|---|---|---|---|",
        )

    def _is_supported_workflow_summary_content(self, content: str) -> bool:
        """Return whether remaining content is a supported workflow summary layout."""
        blocks = self._summary_blocks(content)
        if len(blocks) != 10:
            return False
        if blocks[0] != ["### Overview"]:
            return False
        if not self._matches_table(
            blocks[1],
            header="| Open | In progress | MR opened | Failed | Done |",
            separator="|---|---|---|---|---|",
        ):
            return False
        if blocks[2] != ["### Needs Attention"]:
            return False
        if blocks[3] != ["No items."] and not self._matches_table(
            blocks[3],
            header="| Item | File | Priority | Next Step | Summary |",
            separator="|---|---|---|---|---|",
        ):
            return False
        if blocks[4] != ["### In Flight"]:
            return False
        if blocks[5] != ["No items."] and not self._matches_table(
            blocks[5],
            header="| Item | Status | Priority | Review Summary |",
            separator="|---|---|---|---|",
        ):
            return False
        if blocks[6] != ["### Completed"]:
            return False
        if blocks[7] != ["No items."] and not self._matches_table(
            blocks[7],
            header="| Item | Priority | Summary |",
            separator="|---|---|---|",
        ):
            return False
        if blocks[8] != ["### Work Type Breakdown"]:
            return False
        if blocks[9] == ["No items."]:
            return True
        return self._matches_table(
            blocks[9],
            header="| Work Type | Count |",
            separator="|---|---|",
        )

    def _summary_blocks(self, content: str) -> list[list[str]]:
        """Split one summary-content string into normalized blocks."""
        blocks: list[list[str]] = []
        current: list[str] = []
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line:
                if current:
                    blocks.append(current)
                    current = []
                continue
            current.append(line)
        if current:
            blocks.append(current)
        return blocks

    def _matches_table(self, lines: list[str], *, header: str, separator: str) -> bool:
        """Return whether normalized lines match one supported markdown table."""
        if len(lines) < 2:
            return False
        if lines[0] != header or lines[1] != separator:
            return False
        return all(line.startswith("| ") and line.endswith(" |") for line in lines[2:])

    def _redistribute_workflow_items(
        self,
        sections: list[DashboardSection],
    ) -> list[DashboardSection]:
        """Rebuild standard workflow sections from parsed items."""
        review_items: list[DashboardItem] = []
        workflow_items: list[DashboardItem] = []
        for section in sections:
            if section.key == "merge_request_reviews":
                review_items.extend(section.items)
            else:
                workflow_items.extend(section.items)

        redistributed = {
            key: DashboardSection(key=key, title=SECTION_TITLES[key], items=[])
            for key in SECTION_ORDER
        }
        redistributed["merge_request_reviews"].items = review_items
        for item in workflow_items:
            redistributed[section_key_for_item(item)].items.append(item)
        return [redistributed[key] for key in SECTION_ORDER]
