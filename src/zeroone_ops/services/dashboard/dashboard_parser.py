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
    DashboardManifest,
    DashboardPolicyState,
    DashboardPolicyView,
    DashboardSection,
    build_dashboard_manifest,
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
_MANIFEST_BLOCK_PATTERN = re.compile(
    (
        r"<details>\n"
        r"<summary><code>zeroone-dashboard-manifest</code> machine state</summary>\n\n"
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
        manifest = self._extract_manifest(body)
        self._validate_manifest(
            manifest=manifest,
            sections=sections,
            schema_version=schema_version,
        )
        return DashboardDocument(
            issue_id=issue_id,
            issue_iid=issue_iid,
            issue_url=issue_url,
            title=title,
            sections=sections,
            schema_version=schema_version,
            manifest=build_dashboard_manifest(sections),
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

    def _extract_manifest(self, body: str) -> DashboardManifest | None:
        """Return the canonical dashboard manifest when present."""
        match = _MANIFEST_BLOCK_PATTERN.search(body)
        if match is None:
            return None
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as error:
            raise DashboardParseError(
                "Dashboard manifest block contained invalid JSON."
            ) from error
        return DashboardManifest.model_validate(payload)

    def _validate_manifest(
        self,
        *,
        manifest: DashboardManifest | None,
        sections: list[DashboardSection],
        schema_version: int,
    ) -> None:
        """Validate canonical recovered state against the dashboard manifest when required."""
        if schema_version < CURRENT_DASHBOARD_SCHEMA_VERSION:
            return
        if manifest is None:
            raise DashboardParseError(
                "Current-schema dashboard is missing the dashboard manifest block."
            )
        expected_manifest = build_dashboard_manifest(sections)
        if manifest != expected_manifest:
            raise DashboardParseError(
                "Dashboard manifest did not match the recovered structured state."
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
        hidden_items: list[DashboardItem] = []
        normalized_content = content
        if section_key == "open_candidates":
            hidden_items = self._extract_hidden_workflow_items(content)
            normalized_content = _HIDDEN_WORKFLOW_ITEMS_BLOCK_PATTERN.sub("", content).strip()
        matches = list(_ITEM_BLOCK_PATTERN.finditer(normalized_content))
        if not matches:
            if self._is_tolerated_projection_content(normalized_content):
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
        if not self._is_tolerated_projection_content(remaining):
            raise DashboardParseError("Dashboard section contained unsupported free-form content.")
        return self._merge_items_by_id(parsed, hidden_items)

    def _is_tolerated_projection_content(self, content: str) -> bool:
        """Return whether remaining content looks like projection text, not free-form prose."""
        stripped = content.strip()
        if not stripped:
            return True
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if not lines:
            return True
        return all(
            line == "No items."
            or line.startswith("### ")
            or (line.startswith("|") and line.endswith("|"))
            or self._is_overflow_note(line)
            for line in lines
        )

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
