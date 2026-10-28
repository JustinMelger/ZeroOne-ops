"""Internal batch-sync decisions and outcomes; none are persisted work-item schema."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from zeroone_ops.models.finding_batch_promotion import FindingBatchDecisionReason
from zeroone_ops.models.finding_sync import FindingSyncRecord
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.work_item import WorkItemState, WorkItemStatus

type BatchSyncWriteAction = Literal["created", "updated", "unchanged", "suppressed"]


@dataclass(frozen=True)
class BatchSyncContext:
    """Carry one run's explicit policy, capacity, and persistence inputs."""

    repository_scope: str
    policy_state: PolicyState
    run_id: str
    now: datetime | None
    persist: bool = True
    max_active_work_items: int = 10
    max_findings_per_work_item: int = 5
    source_priorities: Mapping[str, int] | None = None


@dataclass(frozen=True)
class PreparedBatchWorkItem:
    """Retain original authority alongside pure observation/reconciliation decisions."""

    original: FindingSyncRecord
    work_item: WorkItemState
    reconcilable: bool
    capacity_eligible: bool = False
    selection_reason: FindingBatchDecisionReason | None = None


@dataclass(frozen=True)
class BatchProjectionOutcome:
    """Report a guarded projection or preview without modifying caller counters."""

    previous_status: WorkItemStatus
    record: FindingSyncRecord | None = None
    write_action: BatchSyncWriteAction | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatchCreationOutcome:
    """Separate creation/rediscovery evidence from its aggregate reporting."""

    record: FindingSyncRecord | None = None
    selected_member_count: int = 0
    write_action: BatchSyncWriteAction | None = None
    backlog_reason_counts: Mapping[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
