"""Render the derived GitHub operational summary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse


@dataclass(frozen=True)
class GitHubOperationalSummaryEntry:
    """Represent one linked work item in the derived summary."""

    title: str
    web_url: str
    status: str
    updated_at: datetime | None = None


@dataclass(frozen=True)
class GitHubFindingSyncObservation:
    """Represent the bounded latest-finding-sync observation for the summary."""

    observed_at: datetime
    total_findings: int
    promoted_findings: int
    backlog_only_findings: int
    severity_counts: dict[str, int]
    backlog_reason_counts: dict[str, int]


@dataclass(frozen=True)
class GitHubOperationalSummaryView:
    """Represent the complete read-only GitHub operational summary view."""

    policy_issue_url: str | None
    work_item_counts: dict[str, int]
    active_change_requests: list[GitHubOperationalSummaryEntry]
    recent_outcomes: list[GitHubOperationalSummaryEntry]
    latest_finding_sync: GitHubFindingSyncObservation | None


class GitHubOperationalSummaryRenderer:
    """Render a compact, non-authoritative GitHub operational summary."""

    def render(self, view: GitHubOperationalSummaryView) -> str:
        """Render one derived GitHub operational summary issue body."""
        lines = [
            "Read-only operational overview for ZeroOne Ops.",
            "Work-item issues and the policy issue remain authoritative.",
            "",
            "## Overview",
            "",
        ]
        lines.extend(self._render_work_item_counts(view.work_item_counts))
        lines.extend(["", "## Active Remediation PRs", ""])
        lines.extend(
            self._render_entries(
                view.active_change_requests, empty="No active remediation pull requests."
            )
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
        """Render the current authoritative open work-item counts."""
        labels = {
            "candidate": "Candidate",
            "approved": "Ready",
            "in_progress": "In progress",
            "blocked": "Blocked",
        }
        return [f"- {label}: `{counts.get(status, 0)}`" for status, label in labels.items()]

    def _render_entries(
        self,
        entries: list[GitHubOperationalSummaryEntry],
        *,
        empty: str,
    ) -> list[str]:
        """Render a bounded list of linked derived entries."""
        if not entries:
            return [empty]
        return [self._render_entry(entry) for entry in entries]

    def _render_entry(self, entry: GitHubOperationalSummaryEntry) -> str:
        """Render one entry without allowing provider text to change Markdown structure."""
        title = _escape_markdown_text(entry.title)
        destination = _safe_link_destination(entry.web_url)
        rendered_title = f"[{title}](<{destination}>)" if destination is not None else title
        return f"- {rendered_title} - `{_escape_inline_code(entry.status)}`"

    def _render_finding_sync(
        self,
        observation: GitHubFindingSyncObservation | None,
    ) -> list[str]:
        """Render the latest persisted finding-sync observation when available."""
        if observation is None:
            return ["No finding sync has been observed yet."]
        lines = [
            f"- Observed: `{observation.observed_at.isoformat()}`",
            f"- Findings: `{observation.total_findings}`",
            f"- Promoted: `{observation.promoted_findings}`",
            f"- Backlog only: `{observation.backlog_only_findings}`",
            f"- Severities: {_render_counts(observation.severity_counts)}",
            f"- Backlog reasons: {_render_counts(observation.backlog_reason_counts)}",
        ]
        return lines

    def _render_state_block(
        self,
        observation: GitHubFindingSyncObservation | None,
    ) -> list[str]:
        """Render the bounded derived observation needed by later summary refreshes."""
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


def _finding_sync_payload(observation: GitHubFindingSyncObservation) -> dict[str, object]:
    """Serialize the derived observation without changing its visible representation."""
    return {
        "observed_at": observation.observed_at.isoformat(),
        "total_findings": observation.total_findings,
        "promoted_findings": observation.promoted_findings,
        "backlog_only_findings": observation.backlog_only_findings,
        "severity_counts": observation.severity_counts,
        "backlog_reason_counts": observation.backlog_reason_counts,
    }


def _escape_markdown_text(value: str) -> str:
    """Return one single-line Markdown text value with link delimiters escaped."""
    collapsed = " ".join(value.splitlines())
    return collapsed.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _escape_inline_code(value: str) -> str:
    """Return one single-line Markdown inline-code value."""
    return " ".join(value.splitlines()).replace("`", "'")


def _safe_link_destination(value: str) -> str | None:
    """Return an absolute HTTP(S) URL that is safe inside a Markdown destination."""
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
