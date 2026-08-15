"""Provider-neutral models for derived operational summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class FindingSyncObservation:
    """Represent the bounded latest-finding-sync observation for a summary."""

    observed_at: datetime
    total_findings: int
    promoted_findings: int
    backlog_only_findings: int
    severity_counts: dict[str, int]
    backlog_reason_counts: dict[str, int]
    policy_deferred_count: int = 0
    capacity_deferred_count: int = 0
    policy_reactivated_count: int = 0
    no_longer_detected_count: int = 0
    projection_warning_count: int = 0


@dataclass(frozen=True)
class OperationalSummaryEntry:
    """Represent one linked item in a derived operational summary."""

    title: str
    web_url: str
    status: str
    updated_at: datetime | None = None


@dataclass(frozen=True)
class OperationalSummaryWorkItem:
    """Represent the provider-neutral fields needed to render one work item."""

    title: str
    web_url: str
    status: str
    is_open: bool
    updated_at: datetime | None = None
    linked_change_request_url: str | None = None


@dataclass(frozen=True)
class OperationalSummaryView:
    """Represent the complete read-only derived operational-summary view."""

    policy_issue_url: str | None
    work_item_counts: dict[str, int]
    active_change_requests: list[OperationalSummaryEntry]
    recent_outcomes: list[OperationalSummaryEntry]
    latest_finding_sync: FindingSyncObservation | None
    active_change_requests_omitted_count: int = 0


@dataclass(frozen=True)
class OperationalSummaryVocabulary:
    """Provide provider-native terminology without changing summary structure."""

    active_change_requests_heading: str
    active_change_requests_empty: str
    active_change_requests_omitted: str


GITHUB_OPERATIONAL_SUMMARY_VOCABULARY = OperationalSummaryVocabulary(
    active_change_requests_heading="Active Remediation PRs",
    active_change_requests_empty="No active remediation pull requests.",
    active_change_requests_omitted="additional active remediation pull requests are omitted.",
)

GITLAB_OPERATIONAL_SUMMARY_VOCABULARY = OperationalSummaryVocabulary(
    active_change_requests_heading="Active Remediation MRs",
    active_change_requests_empty="No active remediation merge requests.",
    active_change_requests_omitted="additional active remediation merge requests are omitted.",
)
