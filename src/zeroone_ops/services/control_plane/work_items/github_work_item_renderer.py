"""Render deterministic GitHub work-item issue bodies."""

from __future__ import annotations

import json

from zeroone_ops.models.work_item import WorkItemState


class GitHubWorkItemRenderer:
    """Render authoritative GitHub work-item issues."""

    AUTHORITATIVE_WORK_ITEM_LABEL = "zeroone-work-item"

    def render_title(self, work_item: WorkItemState) -> str:
        """Render one compact provider-local work-item title."""
        return f"ZeroOne Ops: {work_item.summary}"

    def render_body(self, work_item: WorkItemState) -> str:
        """Render one deterministic GitHub work-item issue body."""
        lines = [
            "Machine-managed ZeroOne Ops work item.",
            "",
            "This issue is the authoritative GitHub record for one promoted work item.",
            "Direct edits to the machine state block are not authoritative.",
            "",
            "## Summary",
            "",
            work_item.summary,
        ]
        if work_item.detail is not None:
            lines.extend(["", "## Detail", "", work_item.detail])
        lines.extend(
            [
                "",
                "## Work Item",
                "",
                f"- Kind: `{work_item.kind}`",
                f"- Status: `{work_item.status}`",
                f"- Source: `{work_item.source.source}`",
                f"- Source item key: `{work_item.source.source_item_key}`",
            ]
        )
        if work_item.source.repository_scope is not None:
            lines.append(f"- Repository scope: `{work_item.source.repository_scope}`")
        if work_item.severity is not None:
            lines.append(f"- Severity: `{work_item.severity}`")
        if work_item.file_path is not None:
            lines.append(f"- File: `{work_item.file_path}`")
        if work_item.line is not None:
            lines.append(f"- Line: `{work_item.line}`")
        lines.extend(["", "## Linked Change Request", ""])
        if work_item.linked_change_request is None:
            lines.append("No linked change request.")
        else:
            lines.extend(
                [
                    f"- Number: `{work_item.linked_change_request.number}`",
                    f"- URL: {work_item.linked_change_request.web_url}",
                ]
            )
        lines.extend(["", "## Review Projection", ""])
        if work_item.projected_review is None:
            lines.append("No projected review status.")
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
