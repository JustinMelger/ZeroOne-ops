"""Provider-neutral work-item label vocabulary and query indexes."""

from __future__ import annotations

from zeroone_ops.models.work_item import WorkItemState

AUTHORITATIVE_WORK_ITEM_LABEL = "zeroone-work-item"


def work_item_status_label(status: str) -> str:
    """Return the provider-native index label for one work-item status."""
    return f"zeroone-status:{status}"


def work_item_source_label(source_id: str) -> str:
    """Return the provider-native index label for one normalized source."""
    return f"zeroone-source:{source_id}"


def render_work_item_labels(work_item: WorkItemState) -> list[str]:
    """Return the complete label projection for one authoritative work item."""
    return [
        AUTHORITATIVE_WORK_ITEM_LABEL,
        work_item_status_label(work_item.status),
        work_item_source_label(work_item.source.source),
    ]


def work_item_source_query_labels(source_id: str) -> list[str]:
    """Return the narrow server-side indexes for one open identity lookup."""
    return [AUTHORITATIVE_WORK_ITEM_LABEL, work_item_source_label(source_id)]


def dismissed_work_item_query_labels() -> list[str]:
    """Return the narrow server-side indexes for closed dismissal tombstones."""
    return [AUTHORITATIVE_WORK_ITEM_LABEL, work_item_status_label("dismissed")]
