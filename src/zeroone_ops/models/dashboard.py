"""Dashboard models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

CURRENT_DASHBOARD_SCHEMA_VERSION = 2
DASHBOARD_SCHEMA_MARKER = (
    f"<!-- zeroone-ops:dashboard-schema:v{CURRENT_DASHBOARD_SCHEMA_VERSION} -->"
)

DashboardStatus = Literal[
    "open",
    "in_progress",
    "mr_opened",
    "done",
    "rejected",
    "ignored",
    "failed",
]

DashboardAutomationStatus = Literal[
    "eligible for automation",
    "excluded from automation",
    "blocked by severity policy",
    "blocked by safety guard",
]

DashboardSectionKey = Literal[
    "open_candidates",
    "in_progress",
    "merge_requests_opened",
    "completed",
    "merge_request_reviews",
    "rejected_or_ignored",
    "recent_failures",
]


SECTION_TITLES: dict[DashboardSectionKey, str] = {
    "open_candidates": "Open Candidates",
    "in_progress": "In Progress",
    "merge_requests_opened": "Merge Requests Opened",
    "completed": "Completed",
    "merge_request_reviews": "Merge Request Reviews",
    "rejected_or_ignored": "Rejected Or Ignored",
    "recent_failures": "Recent Failures",
}

SECTION_ORDER: tuple[DashboardSectionKey, ...] = (
    "open_candidates",
    "in_progress",
    "merge_requests_opened",
    "completed",
    "merge_request_reviews",
    "rejected_or_ignored",
    "recent_failures",
)


class DashboardSeverityPolicyEntry(BaseModel):
    """Represent one rendered remediation severity-policy entry."""

    severity: Literal["low", "medium", "high"]
    enabled: bool
    reason: str | None = None


class DashboardSeverityPolicyStateEntry(BaseModel):
    """Represent one canonical dashboard-backed severity policy entry."""

    severity: Literal["low", "medium", "high"]
    enabled: bool
    reason: str | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None
    note_id: int | None = None


class DashboardIssueClassPolicyStateEntry(BaseModel):
    """Represent one canonical dashboard-backed issue-class policy entry."""

    source: str
    issue_key: str
    reason: str
    updated_at: datetime | None = None
    updated_by: str | None = None
    note_id: int | None = None


class DashboardIssueClassExclusionEntry(BaseModel):
    """Represent one rendered excluded issue-class entry."""

    source: str
    issue_key: str
    matching_items_count: int = 0
    reason: str


class DashboardIssueClassInventoryEntry(BaseModel):
    """Represent one rendered grouped issue-class inventory entry."""

    source: str
    issue_key: str
    matching_items_count: int
    severities_present: list[str] = Field(default_factory=list)
    source_severities_present: list[str] = Field(default_factory=list)
    automation_status: DashboardAutomationStatus
    reason: str | None = None


class DashboardPolicyView(BaseModel):
    """Represent the rendered operator-policy view for the dashboard."""

    severity_policy: list[DashboardSeverityPolicyEntry] = Field(default_factory=list)
    excluded_issue_classes: list[DashboardIssueClassExclusionEntry] = Field(default_factory=list)
    issue_class_inventory: list[DashboardIssueClassInventoryEntry] = Field(default_factory=list)


class DashboardPolicyState(BaseModel):
    """Represent the canonical machine-owned dashboard policy state."""

    severity_policy: list[DashboardSeverityPolicyStateEntry] = Field(default_factory=list)
    issue_class_exclusions: list[DashboardIssueClassPolicyStateEntry] = Field(default_factory=list)


class DashboardManifest(BaseModel):
    """Represent the machine-managed dashboard integrity manifest."""

    section_item_counts: dict[DashboardSectionKey, int] = Field(default_factory=dict)
    workflow_item_count: int = 0
    total_item_count: int = 0


class DashboardItem(BaseModel):
    """Represent one structured dashboard item."""

    id: str
    source: str
    type: str
    status: DashboardStatus
    title: str
    summary: str
    priority: str
    source_reference: str
    file: str | None = None
    line: int | None = None
    rule: str | None = None
    severity: str | None = None
    source_severity: str | None = None
    automation_severity: str | None = None
    validation_commands: list[str] = Field(default_factory=list)
    expected_change: str | None = None
    constraints: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    pipeline_id: int | None = None
    job_id: int | None = None
    job_name: str | None = None
    branch_name: str | None = None
    last_run_id: str | None = None
    status_updated_at: datetime | None = None
    commit_sha: str | None = None
    merge_request_iid: int | None = None
    merge_request_url: str | None = None
    upstream_active: bool | None = None
    reviewed_head_sha: str | None = None
    review_status: str | None = None
    review_findings_count: int | None = None
    review_feedback_summary: str | None = None
    review_follow_up_lines: list[str] = Field(default_factory=list)
    review_feedback_updated_at: datetime | None = None
    review_confidence: float | None = None
    review_confidence_reason: str | None = None
    retry_count: int | None = None
    retry_eligible: bool | None = None
    retry_block_reason: str | None = None
    log_excerpt: str | None = None


class DashboardSection(BaseModel):
    """Represent one rendered dashboard section."""

    key: DashboardSectionKey
    title: str
    items: list[DashboardItem] = Field(default_factory=list)


class DashboardDocument(BaseModel):
    """Represent the structured dashboard issue body."""

    issue_id: int
    issue_iid: int
    issue_url: str
    title: str
    sections: list[DashboardSection]
    schema_version: int = CURRENT_DASHBOARD_SCHEMA_VERSION
    manifest: DashboardManifest | None = None
    policy_state: DashboardPolicyState = Field(default_factory=DashboardPolicyState)
    policy_view: DashboardPolicyView = Field(default_factory=DashboardPolicyView)

    def items_by_id(self) -> dict[str, DashboardItem]:
        """Return dashboard items keyed by ID."""
        return {item.id: item for section in self.sections for item in section.items}


def section_key_for_item(item: DashboardItem) -> DashboardSectionKey:
    """Map one dashboard item to its section."""
    if item.type == "review_status" or item.source == "pull_request_review":
        return "merge_request_reviews"
    if item.status == "open":
        return "open_candidates"
    if item.status == "in_progress":
        return "in_progress"
    if item.status == "mr_opened":
        return "merge_requests_opened"
    if item.status == "done":
        return "completed"
    if item.status in {"rejected", "ignored"}:
        return "rejected_or_ignored"
    return "recent_failures"


def empty_sections() -> list[DashboardSection]:
    """Build empty sections in deterministic order."""
    return [DashboardSection(key=key, title=SECTION_TITLES[key], items=[]) for key in SECTION_ORDER]


def build_dashboard_manifest(sections: list[DashboardSection]) -> DashboardManifest:
    """Build the canonical dashboard integrity manifest from sections."""
    section_item_counts = {section.key: len(section.items) for section in sections}
    workflow_item_count = sum(
        count for key, count in section_item_counts.items() if key != "merge_request_reviews"
    )
    total_item_count = sum(section_item_counts.values())
    return DashboardManifest(
        section_item_counts=section_item_counts,
        workflow_item_count=workflow_item_count,
        total_item_count=total_item_count,
    )
