"""Select eligible remediation work items without provider dependencies."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath

from zeroone_ops.models.work_item import WorkItemState

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def is_remediation_execution_eligible(work_item: WorkItemState) -> bool:
    """Return whether one open work item is eligible for execution selection."""
    if work_item.kind != "remediation" or work_item.status not in {
        "approved",
        "review_revision_queued",
    }:
        return False
    if work_item.status == "approved" and work_item.linked_change_request is not None:
        return False
    if work_item.status == "review_revision_queued" and (
        work_item.claim is not None
        or work_item.linked_change_request is None
        or work_item.projected_review is None
        or work_item.projected_review.feedback is None
    ):
        return False
    return _is_safe_repository_path(work_item.file_path)


def remediation_execution_selection_key(
    work_item: WorkItemState,
    *,
    created_at: datetime | None,
    provider_issue_number: int,
) -> tuple[int, int, datetime, int]:
    """Return the stable provider-neutral order for one executable work item."""
    severity = work_item.severity or "low"
    return (
        0 if work_item.status == "review_revision_queued" else 1,
        _SEVERITY_ORDER.get(severity.lower(), len(_SEVERITY_ORDER)),
        created_at or datetime.max.replace(tzinfo=UTC),
        provider_issue_number,
    )


def _is_safe_repository_path(file_path: str | None) -> bool:
    """Return whether one stored work-item path remains within the repository."""
    if not file_path:
        return False
    path = PurePosixPath(file_path)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts
