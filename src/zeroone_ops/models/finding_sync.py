"""Provider-neutral finding-sync outcome models."""

from dataclasses import dataclass


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
