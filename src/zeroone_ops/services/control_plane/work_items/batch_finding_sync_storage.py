"""Internal batch storage contract and shared indexed discovery."""

from collections.abc import Callable
from typing import Protocol

from zeroone_ops.models.finding_sync import (
    FindingSyncInventory,
    FindingSyncRecord,
    FindingSyncWriteResult,
)
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.work_items.finding_sync_storage import FindingSyncStorage
from zeroone_ops.services.control_plane.work_items.work_item_labels import (
    AUTHORITATIVE_WORK_ITEM_LABEL,
    batch_identity_label,
    work_item_status_label,
)


def inventory_records(inventory: FindingSyncInventory) -> tuple[FindingSyncRecord, ...]:
    """Deduplicate repeated snapshots while retaining contradictory records for conflict checks."""
    records = (
        *inventory.open_work_items,
        *inventory.policy_deferred_work_items,
        *inventory.capacity_deferred_work_items,
        *inventory.dismissed_work_items,
        *inventory.closed_nonterminal_batches,
    )
    grouped: dict[int, list[FindingSyncRecord]] = {}
    for record in records:
        bucket = grouped.setdefault(record.issue_number, [])
        if record not in bucket:
            bucket.append(record)
    return tuple(record for number in sorted(grouped) for record in grouped[number])


class BatchFindingSyncStorage(FindingSyncStorage, Protocol):
    """Expose batch-only discovery without changing deployed sync reads."""

    def load_batch_inventory(self, *, repository_scope: str) -> FindingSyncInventory:
        """Load strict ownership inventory, including closed nonterminal batches."""
        ...

    def read_work_item(self, *, repository_scope: str, issue_number: int) -> FindingSyncRecord:
        """Re-read exact authority and native closure, rejecting malformed state."""
        ...

    def rediscover_batch(
        self, *, repository_scope: str, work_item_id: str
    ) -> tuple[FindingSyncRecord, ...]:
        """Find exact assigned identity in both issue states without creating work."""
        ...

    def create_work_item(
        self, *, repository_scope: str, work_item: WorkItemState
    ) -> FindingSyncWriteResult:
        """Perform one create after shared ownership authorization, without retries."""
        ...


def load_batch_inventory(
    list_records: Callable[[bool, list[str]], tuple[FindingSyncRecord, ...]],
) -> FindingSyncInventory:
    """Query nonterminal status indexes, never general closed issue history."""
    root = [AUTHORITATIVE_WORK_ITEM_LABEL]
    open_records = list_records(True, root)
    deferred = list_records(False, [*root, work_item_status_label("policy_deferred")])
    capacity = list_records(False, [*root, work_item_status_label("capacity_deferred")])
    dismissed = list_records(False, [*root, work_item_status_label("dismissed")])
    closed_batches: list[FindingSyncRecord] = []
    for status in (
        "candidate",
        "approved",
        "in_progress",
        "blocked",
        "review_feedback_required",
        "review_revision_queued",
    ):
        closed_batches.extend(
            record
            for record in list_records(False, [*root, work_item_status_label(status)])
            if record.work_item.batch is not None
            and record.work_item.status not in {"completed", "dismissed"}
        )
    return FindingSyncInventory(
        open_work_items=open_records,
        policy_deferred_work_items=deferred,
        capacity_deferred_work_items=capacity,
        dismissed_work_items=dismissed,
        closed_nonterminal_batches=tuple(closed_batches),
    )


def rediscover_batch(
    work_item_id: str,
    list_records: Callable[[bool, list[str]], tuple[FindingSyncRecord, ...]],
) -> tuple[FindingSyncRecord, ...]:
    """Verify label hits against persisted identity; mismatches make discovery unsafe."""
    labels = [AUTHORITATIVE_WORK_ITEM_LABEL, batch_identity_label(work_item_id)]
    records = (*list_records(True, labels), *list_records(False, labels))
    if any(
        record.work_item.work_item_id != work_item_id or record.work_item.batch is None
        for record in records
    ):
        raise ValueError("Batch identity index disagrees with authoritative state.")
    unique: dict[int, FindingSyncRecord] = {}
    for record in records:
        previous = unique.setdefault(record.issue_number, record)
        if previous != record:
            raise ValueError("Batch identity discovery changed during lookup.")
    return tuple(unique.values())
