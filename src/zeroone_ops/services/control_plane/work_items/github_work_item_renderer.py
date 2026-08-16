"""Render deterministic GitHub work-item issue bodies."""

from __future__ import annotations

import json
from pathlib import Path

from zeroone_ops.models.remediation import remediation_source_display_name
from zeroone_ops.models.work_item import WorkItemState, work_item_resolution_display_name
from zeroone_ops.services.control_plane.work_items.work_item_labels import (
    AUTHORITATIVE_WORK_ITEM_LABEL as WORK_ITEM_LABEL,
)
from zeroone_ops.services.control_plane.work_items.work_item_labels import (
    render_work_item_labels,
)


class GitHubWorkItemRenderer:
    """Render authoritative GitHub work-item issues."""

    AUTHORITATIVE_WORK_ITEM_LABEL = WORK_ITEM_LABEL
    _MAX_TITLE_LENGTH = 120

    def render_title(self, work_item: WorkItemState) -> str:
        """Render one compact provider-local work-item title."""
        diagnostic_code = work_item.remediation_context.diagnostic_code
        if diagnostic_code is not None and work_item.file_path is not None:
            title = f"ZeroOne Ops: {diagnostic_code} in {Path(work_item.file_path).name}"
            line = work_item.line
        else:
            title = f"ZeroOne Ops: {self._finding_description(work_item)}"
            line = None
        return _title_with_location(
            title,
            line=line,
            maximum_length=self._MAX_TITLE_LENGTH,
        )

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
                f"- Source: {remediation_source_display_name(work_item.source.source)}",
            ]
        )
        if work_item.resolution is not None:
            lines.append(f"- Resolution: {work_item_resolution_display_name(work_item.resolution)}")
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
                    (
                        f"- Review note URL: {work_item.projected_review.review_note_url}"
                        if work_item.projected_review.review_note_url is not None
                        else "- Review note URL: unavailable"
                    ),
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
                    f"- Status: `{failure.status}`",
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
            if failure.validation_outcome is not None:
                lines.append(f"- Validation outcome: `{failure.validation_outcome}`")
            if failure.execution_url is not None:
                lines.append(f"- Run: [View workflow logs]({failure.execution_url})")
        if work_item.policy_deferral is not None:
            deferral = work_item.policy_deferral
            lines.extend(
                [
                    "",
                    "## Policy Deferral",
                    "",
                    f"- Reason: `{deferral.reason}`",
                    f"- Sync run: `{deferral.run_id}`",
                    f"- Recorded: `{deferral.occurred_at.isoformat()}`",
                ]
            )
        if work_item.capacity_deferral is not None:
            capacity_deferral = work_item.capacity_deferral
            lines.extend(
                [
                    "",
                    "## Capacity Deferral",
                    "",
                    f"- Reason: `{capacity_deferral.reason}`",
                    f"- Sync run: `{capacity_deferral.run_id}`",
                    f"- Recorded: `{capacity_deferral.occurred_at.isoformat()}`",
                ]
            )
        if work_item.status == "blocked":
            lines.extend(self._render_recovery_instructions(work_item))
        lines.extend(["", "## Machine State", ""])
        lines.extend(self._render_state_block(work_item))
        return "\n".join(lines).rstrip() + "\n"

    def render_labels(self, work_item: WorkItemState) -> list[str]:
        """Render the provider-local label projection for one work item."""
        return render_work_item_labels(work_item)

    def _finding_description(self, work_item: WorkItemState) -> str:
        """Return the most concrete available operator-facing finding text."""
        if work_item.detail is not None and _looks_like_template(work_item.summary):
            return work_item.detail
        return work_item.summary

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
            "Requeue for remediation: `/zeroone remediation requeue`",
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


def _title_with_location(value: str, *, line: int | None, maximum_length: int) -> str:
    """Append a stable compact location while preserving the title bound."""
    if line is None:
        return _truncate_title(value, maximum_length=maximum_length)
    suffix = f":{line}"
    if len(suffix) >= maximum_length:
        return _truncate_title(f"{value} {suffix}", maximum_length=maximum_length)
    return f"{_truncate_title(value, maximum_length=maximum_length - len(suffix))}{suffix}"
