"""Render provider-neutral derived operational summaries."""

from __future__ import annotations

import json
from urllib.parse import urlparse

from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    FindingSyncObservation,
    OperationalSummaryEntry,
    OperationalSummaryView,
    OperationalSummaryVocabulary,
)


class OperationalSummaryRenderer:
    """Render a compact non-authoritative operational summary."""

    def __init__(self, *, vocabulary: OperationalSummaryVocabulary) -> None:
        """Initialize one renderer with provider-native terminology."""
        self.vocabulary = vocabulary

    def render(self, view: OperationalSummaryView) -> str:
        """Render one derived operational-summary issue body."""
        lines = [
            "Read-only operational overview for ZeroOne Ops.",
            "Work-item issues and the policy issue remain authoritative.",
            "",
            "## Overview",
            "",
        ]
        lines.extend(self._render_work_item_counts(view.work_item_counts))
        lines.extend(["", f"## {self.vocabulary.active_change_requests_heading}", ""])
        lines.extend(
            self._render_entries(
                view.active_change_requests,
                empty=self.vocabulary.active_change_requests_empty,
            )
        )
        if view.active_change_requests_omitted_count:
            lines.append(
                "- "
                f"{view.active_change_requests_omitted_count} "
                f"{self.vocabulary.active_change_requests_omitted}"
            )
        lines.extend(["", "## Latest Finding Sync", ""])
        lines.extend(self._render_finding_sync(view.latest_finding_sync))
        lines.extend(["", "## Recent Outcomes", ""])
        lines.extend(
            self._render_entries(view.recent_outcomes, empty="No recent work-item outcomes.")
        )
        lines.extend(["", "## Policy", ""])
        policy_destination = (
            _safe_link_destination(view.policy_issue_url)
            if view.policy_issue_url is not None
            else None
        )
        if policy_destination is None:
            lines.append("No policy issue link is available yet.")
        else:
            lines.append(f"[Open the ZeroOne Ops policy issue](<{policy_destination}>).")
        lines.extend([""])
        lines.extend(self._render_state_block(view.latest_finding_sync))
        return "\n".join(lines).rstrip() + "\n"

    def _render_work_item_counts(self, counts: dict[str, int]) -> list[str]:
        """Render the current authoritative open-work-item counts."""
        labels = {
            "candidate": "Candidate",
            "approved": "Ready",
            "in_progress": "In progress",
            "blocked": "Blocked",
            "capacity_deferred": "Capacity deferred",
        }
        return [f"- {label}: `{counts.get(status, 0)}`" for status, label in labels.items()]

    def _render_entries(
        self,
        entries: list[OperationalSummaryEntry],
        *,
        empty: str,
    ) -> list[str]:
        """Render a bounded list of linked derived entries."""
        if not entries:
            return [empty]
        return [self._render_entry(entry) for entry in entries]

    def _render_entry(self, entry: OperationalSummaryEntry) -> str:
        """Render one entry without allowing provider text to alter Markdown."""
        title = _escape_markdown_text(entry.title)
        destination = _safe_link_destination(entry.web_url)
        rendered_title = f"[{title}](<{destination}>)" if destination is not None else title
        return f"- {rendered_title} - `{_escape_inline_code(entry.status)}`"

    def _render_finding_sync(
        self,
        observation: FindingSyncObservation | None,
    ) -> list[str]:
        """Render the latest persisted finding-sync observation when available."""
        if observation is None:
            return ["Finding-sync details are unavailable until the next successful sync."]
        return [
            f"- Observed: `{observation.observed_at.isoformat()}`",
            f"- Findings: `{observation.total_findings}`",
            f"- Promoted: `{observation.promoted_findings}`",
            f"- Backlog only: `{observation.backlog_only_findings}`",
            f"- Severities: {_render_counts(observation.severity_counts)}",
            f"- Backlog reasons: {_render_counts(observation.backlog_reason_counts)}",
            "- Deferred-work transitions: "
            f"deferred={observation.policy_deferred_count}; "
            f"capacity deferred={observation.capacity_deferred_count}; "
            f"reactivated={observation.policy_reactivated_count}; "
            f"no longer detected={observation.no_longer_detected_count}; "
            f"warnings={observation.projection_warning_count}",
        ]

    def _render_state_block(
        self,
        observation: FindingSyncObservation | None,
    ) -> list[str]:
        """Render the bounded derived observation needed by later refreshes."""
        payload = (
            {"latest_finding_sync": _finding_sync_payload(observation)}
            if observation is not None
            else {"latest_finding_sync": None}
        )
        return [
            "<details>",
            "<summary><code>zeroone-operational-summary-state</code> derived state</summary>",
            "",
            "```json",
            json.dumps(payload, indent=2, sort_keys=True),
            "```",
            "",
            "</details>",
        ]


def _render_counts(counts: dict[str, int]) -> str:
    """Render compact deterministic aggregate counts."""
    if not counts:
        return "none"
    return ", ".join(
        f"`{_escape_inline_code(key)}`: {value}" for key, value in sorted(counts.items())
    )


def _finding_sync_payload(observation: FindingSyncObservation) -> dict[str, object]:
    """Serialize the derived observation without changing its visible representation."""
    return {
        "observed_at": observation.observed_at.isoformat(),
        "total_findings": observation.total_findings,
        "promoted_findings": observation.promoted_findings,
        "backlog_only_findings": observation.backlog_only_findings,
        "severity_counts": observation.severity_counts,
        "backlog_reason_counts": observation.backlog_reason_counts,
        "policy_deferred_count": observation.policy_deferred_count,
        "capacity_deferred_count": observation.capacity_deferred_count,
        "policy_reactivated_count": observation.policy_reactivated_count,
        "no_longer_detected_count": observation.no_longer_detected_count,
        "projection_warning_count": observation.projection_warning_count,
    }


def _escape_markdown_text(value: str) -> str:
    """Return one single-line Markdown text value with link delimiters escaped."""
    collapsed = " ".join(value.splitlines())
    return collapsed.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _escape_inline_code(value: str) -> str:
    """Return one single-line Markdown inline-code value."""
    return " ".join(value.splitlines()).replace("`", "'")


def _safe_link_destination(value: str) -> str | None:
    """Return an absolute HTTP(S) URL safe inside a Markdown destination."""
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or any(character.isspace() for character in value)
        or "<" in value
        or ">" in value
    ):
        return None
    return value
