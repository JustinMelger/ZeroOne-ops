"""Render deterministic GitHub work-item issue bodies."""

from __future__ import annotations

import json
from pathlib import Path

from zeroone_ops.models.work_item import WorkItemState


class GitHubWorkItemRenderer:
    """Render authoritative GitHub work-item issues."""

    AUTHORITATIVE_WORK_ITEM_LABEL = "zeroone-work-item"
    _MAX_TITLE_LENGTH = 120

    def render_title(self, work_item: WorkItemState) -> str:
        """Render one compact provider-local work-item title."""
        diagnostic_code = work_item.remediation_context.diagnostic_code
        if diagnostic_code is not None and work_item.file_path is not None:
            title = f"ZeroOne Ops: {diagnostic_code} in {Path(work_item.file_path).name}"
        else:
            title = f"ZeroOne Ops: {self._finding_description(work_item)}"
        return _truncate_title(title, maximum_length=self._MAX_TITLE_LENGTH)

    def render_body(self, work_item: WorkItemState) -> str:
        """Render one deterministic GitHub work-item issue body."""
        finding_description = self._finding_description(work_item)
        lines = [
            "This issue tracks one remediation candidate managed by ZeroOne Ops.",
            "The collapsed machine state is managed by ZeroOne Ops and may be overwritten on sync.",
            "",
            "## Finding",
            "",
            finding_description,
        ]
        if work_item.detail is not None and work_item.detail != finding_description:
            lines.extend(["", work_item.detail])
        lines.extend(
            [
                "",
                "## Status",
                "",
                f"- Status: `{work_item.status}`",
                f"- Severity: `{work_item.severity or 'unknown'}`",
                f"- Source: {self._source_label(work_item.source.source)}",
            ]
        )
        lines.extend(["", "## Location", ""])
        if work_item.file_path is not None:
            lines.append(f"- File: `{work_item.file_path}`")
        if work_item.line is not None:
            lines.append(f"- Line: `{work_item.line}`")
        if work_item.remediation_context.diagnostic_code is not None:
            lines.append(f"- Rule: `{work_item.remediation_context.diagnostic_code}`")
        if work_item.file_path is None and work_item.line is None:
            lines.append("No repository location is available.")
        lines.extend(["", "## Remediation PR", ""])
        if work_item.linked_change_request is None:
            lines.append("No remediation pull request is linked yet.")
        else:
            lines.extend(
                [
                    f"- Number: `{work_item.linked_change_request.number}`",
                    f"- URL: {work_item.linked_change_request.web_url}",
                ]
            )
        lines.extend(["", "## Review Projection", ""])
        if work_item.projected_review is None:
            lines.append("No remediation PR review has been projected yet.")
        else:
            lines.extend(
                [
                    f"- Classification: `{work_item.projected_review.classification}`",
                    f"- Reviewed SHA: `{work_item.projected_review.reviewed_sha}`",
                    f"- Review note URL: {work_item.projected_review.review_note_url}",
                    (
                        "- Follow-up required: "
                        f"`{'yes' if work_item.projected_review.follow_up_required else 'no'}`"
                    ),
                ]
            )
        if work_item.execution_failure is not None:
            failure = work_item.execution_failure
            lines.extend(
                [
                    "",
                    "## Last Execution",
                    "",
                    "- Status: `blocked`",
                    f"- Stage: `{failure.stage}`",
                    f"- Summary: {failure.summary}",
                    f"- Retries used: `{failure.retry_count}`",
                    f"- Run ID: `{failure.run_id}`",
                    f"- Recorded: `{failure.occurred_at.isoformat()}`",
                ]
            )
            if failure.failed_command is not None:
                lines.append(f"- Command: `{failure.failed_command}`")
            if failure.exit_code is not None:
                lines.append(f"- Exit code: `{failure.exit_code}`")
            if failure.execution_url is not None:
                lines.append(f"- Run: [View workflow logs]({failure.execution_url})")
        if work_item.status == "blocked":
            lines.extend(self._render_recovery_instructions(work_item))
        lines.extend(["", "## Machine State", ""])
        lines.extend(self._render_state_block(work_item))
        return "\n".join(lines).rstrip() + "\n"

    def render_labels(self, work_item: WorkItemState) -> list[str]:
        """Render the provider-local label projection for one work item."""
        labels = [
            self.AUTHORITATIVE_WORK_ITEM_LABEL,
            f"zeroone-status:{work_item.status}",
            f"zeroone-source:{work_item.source.source}",
        ]
        return labels

    def _finding_description(self, work_item: WorkItemState) -> str:
        """Return the most concrete available operator-facing finding text."""
        if work_item.detail is not None and _looks_like_template(work_item.summary):
            return work_item.detail
        return work_item.summary

    def _source_label(self, source: str) -> str:
        """Render known finding sources with operator-facing names."""
        return {
            "ruff-sarif": "Ruff SARIF",
            "sonarqube": "SonarQube",
        }.get(source, source.replace("-", " ").title())

    @staticmethod
    def _render_recovery_instructions(work_item: WorkItemState) -> list[str]:
        """Render compact operator instructions for one blocked remediation item."""
        if work_item.execution_failure is not None:
            blocker = f"This remediation is blocked because {work_item.execution_failure.summary}"
        elif work_item.publication_retry is not None:
            blocker = "This remediation is blocked because change-request publication failed."
        else:
            blocker = "This remediation is blocked and needs an operator decision."
        return [
            "",
            "## Recovery",
            "",
            blocker,
            "",
            "Retry safely: `/zeroone remediation retry`",
            "Stop automation: `/zeroone remediation dismiss`",
        ]

    def _render_state_block(self, work_item: WorkItemState) -> list[str]:
        payload = work_item.model_dump(mode="json", exclude_none=True)
        return [
            "<details>",
            "<summary><code>zeroone-work-item-state</code> machine state</summary>",
            "",
            "```json",
            json.dumps(payload, indent=2, sort_keys=True),
            "```",
            "",
            "</details>",
        ]


def _looks_like_template(value: str) -> bool:
    """Return whether source text still contains an unresolved placeholder."""
    return "{" in value and "}" in value


def _truncate_title(value: str, *, maximum_length: int) -> str:
    """Return a bounded GitHub issue title without splitting a trailing space."""
    if len(value) <= maximum_length:
        return value
    return f"{value[: maximum_length - 3].rstrip()}..."
