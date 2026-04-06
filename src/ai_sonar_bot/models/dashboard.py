"""Dashboard models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DashboardStatus = Literal[
    "open",
    "in_progress",
    "mr_opened",
    "done",
    "rejected",
    "ignored",
    "failed",
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
    validation_commands: list[str] = Field(default_factory=list)
    expected_change: str | None = None
    constraints: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
    pipeline_id: int | None = None
    job_id: int | None = None
    job_name: str | None = None
    commit_sha: str | None = None
    merge_request_iid: int | None = None
    merge_request_url: str | None = None
    reviewed_head_sha: str | None = None
    review_status: str | None = None
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
