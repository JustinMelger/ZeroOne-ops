"""Dashboard markdown parser."""

from __future__ import annotations

import json
import re

from zeroone_ops.models.dashboard import (
    CURRENT_DASHBOARD_SCHEMA_VERSION,
    SECTION_ORDER,
    SECTION_TITLES,
    DashboardDocument,
    DashboardItem,
    DashboardPolicyState,
    DashboardPolicyView,
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


_SCHEMA_MARKER_PATTERN = re.compile(r"<!-- zeroone-ops:dashboard-schema:v(?P<version>\d+) -->")
_POLICY_STATE_BLOCK_PATTERN = re.compile(
    (
        r"<details>\n"
        r"<summary><code>zeroone-policy-state</code> machine state</summary>\n\n"
        r"```json\n(?P<payload>.*?)\n```\n\n"
        r"</details>"
    ),
    re.DOTALL,
)
_HIDDEN_WORKFLOW_ITEMS_BLOCK_PATTERN = re.compile(
    (
        r"<details>\n"
        r"<summary><code>zeroone-workflow-hidden-items</code> machine state</summary>\n\n"
        r"```json\n(?P<payload>.*?)\n```\n\n"
        r"</details>"
    ),
    re.DOTALL,
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
        schema_version = self._extract_schema_version(body)
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
            schema_version=schema_version,
            policy_state=self._extract_policy_state(body),
            policy_view=DashboardPolicyView(),
        )

    def _extract_policy_state(self, body: str) -> DashboardPolicyState:
        """Return the canonical dashboard policy state when present."""
        match = _POLICY_STATE_BLOCK_PATTERN.search(body)
        if match is None:
            return DashboardPolicyState()
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as error:
            raise DashboardParseError(
                "Dashboard policy state block contained invalid JSON."
            ) from error
        return DashboardPolicyState.model_validate(payload)

    def _extract_schema_version(self, body: str) -> int:
        """Return the dashboard schema version or legacy v0 when missing."""
        match = _SCHEMA_MARKER_PATTERN.search(body)
        if match is None:
            return 0
        version = int(match.group("version"))
        if version > CURRENT_DASHBOARD_SCHEMA_VERSION:
            raise DashboardParseError(
                "Dashboard schema version is newer than this parser supports."
            )
        return version

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
        hidden_items: list[DashboardItem] = []
        normalized_content = content
        if section_key == "open_candidates":
            hidden_items = self._extract_hidden_workflow_items(content)
            normalized_content = _HIDDEN_WORKFLOW_ITEMS_BLOCK_PATTERN.sub("", content).strip()
        matches = list(_ITEM_BLOCK_PATTERN.finditer(normalized_content))
        if not matches:
            if self._is_supported_summary_content(section_key, normalized_content):
                return hidden_items
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
        remaining = normalized_content
        for block in normalized_blocks:
            remaining = remaining.replace(block, "", 1)
        if not self._is_supported_summary_content(section_key, remaining):
            raise DashboardParseError("Dashboard section contained unsupported free-form content.")
        return self._merge_items_by_id(parsed, hidden_items)

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
        if len(blocks) == 12:
            return self._matches_legacy_workflow_summary_layout(blocks)
        if len(blocks) != 14:
            return False
        if blocks[0] != ["### Overview"]:
            return False
        if not self._matches_table(
            blocks[1],
            header="| Open | In progress | MR opened | Failed | Done |",
            separator="|---|---|---|---|---|",
        ):
            return False
        if blocks[2] != ["### Queue Auto-fix"]:
            return False
        if blocks[3] != ["No items."] and not self._matches_table_with_optional_overflow(
            blocks[3],
            header="| Item | Area | File | Priority | Next Step | Summary |",
            separator="|---|---|---|---|---|---|",
        ):
            return False
        if blocks[4] != ["### Needs Review"]:
            return False
        if blocks[5] != ["No items."] and not self._matches_table_with_optional_overflow(
            blocks[5],
            header="| Item | Area | File | Priority | Next Step | Summary |",
            separator="|---|---|---|---|---|---|",
        ):
            return False
        if blocks[6] != ["### In Flight"]:
            return False
        if blocks[7] != ["No items."] and not self._matches_table_with_optional_overflow(
            blocks[7],
            header="| Item | Area | Status | Priority | Review Summary |",
            separator="|---|---|---|---|---|",
        ):
            return False
        if blocks[8] != ["### Completed"]:
            return False
        if blocks[9] != ["No items."] and not self._matches_table_with_optional_overflow(
            blocks[9],
            header="| Item | Area | Priority | Summary |",
            separator="|---|---|---|---|",
        ):
            return False
        if blocks[10] != ["### Dismissed"]:
            return False
        if blocks[11] != ["No items."] and not self._matches_table_with_optional_overflow(
            blocks[11],
            header="| Item | Area | Status | Priority | Summary |",
            separator="|---|---|---|---|---|",
        ):
            return False
        if blocks[12] != ["### Work Type Breakdown"]:
            return False
        if blocks[13] == ["No items."]:
            return True
        return self._matches_table(
            blocks[13],
            header="| Work Type | Count |",
            separator="|---|---|",
        )

    def _matches_legacy_workflow_summary_layout(self, blocks: list[list[str]]) -> bool:
        """Return whether blocks match the pre-dismissed workflow summary layout."""
        if blocks[0] != ["### Overview"]:
            return False
        if not self._matches_table(
            blocks[1],
            header="| Open | In progress | MR opened | Failed | Done |",
            separator="|---|---|---|---|---|",
        ):
            return False
        if blocks[2] != ["### Queue Auto-fix"]:
            return False
        if blocks[3] != ["No items."] and not self._matches_table_with_optional_overflow(
            blocks[3],
            header="| Item | Area | File | Priority | Next Step | Summary |",
            separator="|---|---|---|---|---|---|",
        ):
            return False
        if blocks[4] != ["### Needs Review"]:
            return False
        if blocks[5] != ["No items."] and not self._matches_table_with_optional_overflow(
            blocks[5],
            header="| Item | Area | File | Priority | Next Step | Summary |",
            separator="|---|---|---|---|---|---|",
        ):
            return False
        if blocks[6] != ["### In Flight"]:
            return False
        if blocks[7] != ["No items."] and not self._matches_table_with_optional_overflow(
            blocks[7],
            header="| Item | Area | Status | Priority | Review Summary |",
            separator="|---|---|---|---|---|",
        ):
            return False
        if blocks[8] != ["### Completed"]:
            return False
        if blocks[9] != ["No items."] and not self._matches_table_with_optional_overflow(
            blocks[9],
            header="| Item | Area | Priority | Summary |",
            separator="|---|---|---|---|",
        ):
            return False
        if blocks[10] != ["### Work Type Breakdown"]:
            return False
        if blocks[11] == ["No items."]:
            return True
        return self._matches_table(
            blocks[11],
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

    def _matches_table_with_optional_overflow(
        self,
        lines: list[str],
        *,
        header: str,
        separator: str,
    ) -> bool:
        """Return whether lines are one supported table plus an optional overflow note."""
        if self._matches_table(lines, header=header, separator=separator):
            return True
        if len(lines) < 4:
            return False
        if not self._is_overflow_note(lines[-1]):
            return False
        return self._matches_table(lines[:-1], header=header, separator=separator)

    def _is_overflow_note(self, line: str) -> bool:
        """Return whether one line is a supported workflow overflow summary note."""
        return bool(re.fullmatch(r"_[0-9]+ more items not shown\._", line))

    def _extract_hidden_workflow_items(self, content: str) -> list[DashboardItem]:
        """Return hidden workflow items persisted in the compact machine-state block."""
        match = _HIDDEN_WORKFLOW_ITEMS_BLOCK_PATTERN.search(content)
        if match is None:
            return []
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as error:
            raise DashboardParseError(
                "Hidden workflow items block contained invalid JSON."
            ) from error
        if not isinstance(payload, list):
            raise DashboardParseError("Hidden workflow items block must contain a JSON list.")
        return [DashboardItem.model_validate(item) for item in payload]

    def _merge_items_by_id(
        self,
        visible_items: list[DashboardItem],
        hidden_items: list[DashboardItem],
    ) -> list[DashboardItem]:
        """Merge visible and hidden workflow items by item ID, preferring visible items."""
        merged = {item.id: item for item in hidden_items}
        for item in visible_items:
            merged[item.id] = item
        return list(merged.values())

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
