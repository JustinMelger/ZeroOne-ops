"""Shared indexed discovery and authoritative finding-sync scope validation."""

from collections.abc import Callable

from zeroone_ops.models.finding_sync import (
    FindingSyncInventory,
    FindingSyncRecord,
)
from zeroone_ops.models.work_item import WorkItemState
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


def require_scoped_work_item(
    state: WorkItemState | None, *, repository_scope: str, error_message: str
) -> WorkItemState:
    """Return original parsed authority or reject missing and cross-repository state."""
    if state is None or state.source.repository_scope != repository_scope:
        raise ValueError(error_message)
    return state


def load_finding_sync_inventory(
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
