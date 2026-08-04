"""Parse bounded derived state from GitHub operational summary issues."""

from __future__ import annotations

import json
import re
from datetime import datetime

from zeroone_ops.services.control_plane.overview.github_operational_summary_renderer import (
    GitHubFindingSyncObservation,
)

_SUMMARY_STATE_BLOCK_PATTERN = re.compile(
    (
        r"<details>\n"
        r"<summary><code>zeroone-operational-summary-state</code> derived state</summary>\n\n"
        r"```json\n(?P<payload>.*?)\n```\n\n"
        r"</details>"
    ),
    re.DOTALL,
)
_MAX_AGGREGATE_COUNT_ENTRIES = 16
_MAX_AGGREGATE_COUNT_KEY_LENGTH = 100


class GitHubOperationalSummaryParser:
    """Read non-authoritative persisted observations from one summary issue."""

    def parse_latest_finding_sync(self, body: str) -> GitHubFindingSyncObservation | None:
        """Return the latest valid derived finding-sync observation when present."""
        match = _SUMMARY_STATE_BLOCK_PATTERN.search(body)
        if match is None:
            return None
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return _parse_observation(payload.get("latest_finding_sync"))


def _parse_observation(value: object) -> GitHubFindingSyncObservation | None:
    """Validate the intentionally small persisted finding-sync observation."""
    if not isinstance(value, dict):
        return None
    observed_at = _parse_timestamp(value.get("observed_at"))
    total_findings = value.get("total_findings")
    promoted_findings = value.get("promoted_findings")
    backlog_only_findings = value.get("backlog_only_findings")
    severity_counts = _parse_counts(value.get("severity_counts"))
    backlog_reason_counts = _parse_counts(value.get("backlog_reason_counts"))
    if observed_at is None or not isinstance(total_findings, int):
        return None
    if not isinstance(promoted_findings, int) or not isinstance(backlog_only_findings, int):
        return None
    if severity_counts is None or backlog_reason_counts is None:
        return None
    return GitHubFindingSyncObservation(
        observed_at=observed_at,
        total_findings=total_findings,
        promoted_findings=promoted_findings,
        backlog_only_findings=backlog_only_findings,
        severity_counts=severity_counts,
        backlog_reason_counts=backlog_reason_counts,
    )


def _parse_timestamp(value: object) -> datetime | None:
    """Parse one timezone-aware persisted timestamp."""
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None else None


def _parse_counts(value: object) -> dict[str, int] | None:
    """Parse one bounded aggregate-count mapping."""
    if not isinstance(value, dict) or len(value) > _MAX_AGGREGATE_COUNT_ENTRIES:
        return None
    counts: dict[str, int] = {}
    for key, count in value.items():
        if (
            not isinstance(key, str)
            or len(key) > _MAX_AGGREGATE_COUNT_KEY_LENGTH
            or not isinstance(count, int)
            or count < 0
        ):
            return None
        counts[key] = count
    return counts
