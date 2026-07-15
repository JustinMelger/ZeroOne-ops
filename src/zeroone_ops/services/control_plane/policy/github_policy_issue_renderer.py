"""Render the GitHub policy issue body."""

from __future__ import annotations

import json

from zeroone_ops.models.dashboard import (
    DashboardIssueClassExclusionEntry,
    DashboardPolicyState,
    DashboardPolicyView,
    DashboardSeverityPolicyEntry,
)


class GitHubPolicyIssueRenderer:
    """Render the compact machine-owned GitHub policy issue body."""

    def render(
        self,
        *,
        policy_state: DashboardPolicyState,
        policy_view: DashboardPolicyView,
    ) -> str:
        """Render one GitHub policy issue body."""
        lines = [
            "Machine-managed repository policy for ZeroOne Ops.",
            "",
            "Use issue comments with the exact `/zeroone policy` prefix to change policy.",
            "Direct edits to this issue body are display-only and not authoritative.",
            "",
            "## Severity Policy",
            "",
        ]
        lines.extend(self._render_severity_policy_table(policy_view.severity_policy))
        lines.extend(["", "## Excluded Issue Classes", ""])
        lines.extend(self._render_excluded_issue_classes_table(policy_view.excluded_issue_classes))
        lines.extend(["", "## Command Reference", ""])
        lines.extend(self._render_command_reference())
        lines.extend(["", "## Notes", ""])
        lines.extend(self._render_notes())
        lines.extend(["", "## Machine State", ""])
        lines.extend(self._render_policy_state_block(policy_state))
        return "\n".join(lines).rstrip() + "\n"

    def _render_policy_state_block(self, policy_state: DashboardPolicyState) -> list[str]:
        payload = policy_state.model_dump(mode="json", exclude_none=True, by_alias=True)
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

    def _render_severity_policy_table(
        self,
        rows: list[DashboardSeverityPolicyEntry],
    ) -> list[str]:
        lines = [
            "| Severity | Status | Reason |",
            "|---|---|---|",
        ]
        for row in rows:
            status = "enabled" if row.enabled else "disabled"
            lines.append(f"| `{row.severity}` | {status} | {row.reason or '-'} |")
        return lines

    def _render_excluded_issue_classes_table(
        self,
        rows: list[DashboardIssueClassExclusionEntry],
    ) -> list[str]:
        if not rows:
            return ["No excluded issue classes."]
        lines = [
            "| Issue Class | Matching Items | Reason |",
            "|---|---|---|",
        ]
        for row in rows:
            lines.append(
                f"| `{row.source} / {row.issue_key}` | {row.matching_items_count} | {row.reason} |"
            )
        return lines

    def _render_command_reference(self) -> list[str]:
        return [
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
        ]

    def _render_notes(self) -> list[str]:
        return [
            "- Accepted commands are replayed in deterministic order.",
            "- Only issue comments are authoritative for policy changes in this slice.",
            (
                "- Malformed or unauthorized commands are visible in logs, "
                "not replied to automatically."
            ),
        ]
