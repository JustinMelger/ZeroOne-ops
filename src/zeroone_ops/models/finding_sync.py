"""Provider-neutral finding-sync outcome models."""

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.work_item import WorkItemState


@dataclass(frozen=True)
class FindingSyncRecord:
    """Represent authoritative work and its provider-neutral issue reference."""

    work_item: WorkItemState
    issue_number: int
    issue_url: str
    is_open: bool


@dataclass(frozen=True)
class FindingSyncInventory:
    """Retain the four ordered inventories inspected by finding sync."""

    open_work_items: tuple[FindingSyncRecord, ...]
    policy_deferred_work_items: tuple[FindingSyncRecord, ...]
    capacity_deferred_work_items: tuple[FindingSyncRecord, ...]
    dismissed_work_items: tuple[FindingSyncRecord, ...]


@dataclass(frozen=True)
class FindingSyncWriteResult:
    """Capture the actual persisted state and existing publication action."""

    record: FindingSyncRecord
    action: Literal["created", "updated", "unchanged", "suppressed"]


@dataclass(frozen=True)
class FindingSyncResult:
    """Summarize one finding publication and reconciliation pass."""

    promoted_count: int
    backlog_only_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    demoted_to_candidate_count: int
    retained_protected_count: int
    stale_demoted_to_candidate_count: int
    stale_retained_protected_count: int
    normalized_severity_counts: dict[str, int]
    enabled_severities: tuple[str, ...]
    backlog_reason_counts: dict[str, int]
    policy_deferred_count: int = 0
    capacity_deferred_count: int = 0
    policy_reactivated_count: int = 0
    no_longer_detected_count: int = 0
    projection_warning_count: int = 0
