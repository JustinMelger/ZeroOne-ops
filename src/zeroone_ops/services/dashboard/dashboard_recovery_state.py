"""Translate GitLab dashboard items to the shared remediation recovery state."""

from __future__ import annotations

from typing import cast

from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.models.finding import RemediationContext
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    WorkItemSourceRef,
    WorkItemState,
    WorkItemStatus,
)

_DASHBOARD_TO_WORK_ITEM_STATUS = {
    "open": "approved",
    "in_progress": "in_progress",
    "change_request_opened": "in_progress",
    "mr_opened": "in_progress",
    "done": "completed",
    "rejected": "dismissed",
    "ignored": "dismissed",
    "failed": "blocked",
}

_WORK_ITEM_TO_DASHBOARD_STATUS = {
    "approved": "open",
    "in_progress": "in_progress",
    "blocked": "failed",
    "completed": "done",
    "dismissed": "rejected",
}


def dashboard_item_to_work_item_state(item: DashboardItem) -> WorkItemState:
    """Build the shared recovery state for one authoritative dashboard item."""
    status = _DASHBOARD_TO_WORK_ITEM_STATUS.get(item.status)
    if status is None:
        raise ValueError(f"Dashboard item {item.id} has unsupported recovery status {item.status}.")
    return WorkItemState(
        work_item_id=item.id,
        kind="remediation",
        status=cast(WorkItemStatus, status),
        source=WorkItemSourceRef(
            source=item.source,
            source_item_key=item.source_reference,
            repository_scope=item.project,
        ),
        summary=item.title,
        detail=item.summary,
        severity=item.automation_severity or item.severity,
        file_path=item.file,
        line=item.line,
        remediation_context=RemediationContext(
            category=item.type,
            diagnostic_code=item.rule,
            validation_commands=list(item.validation_commands),
            expected_change=item.expected_change,
            constraints=item.constraints,
            acceptance_criteria=list(item.acceptance_criteria),
        ),
        linked_change_request=_change_request_ref(item),
        publication_retry=item.publication_retry,
        execution_failure=item.execution_failure,
        attempt_number=item.attempt_number,
        recovery_events=list(item.recovery_events),
        resolution=item.resolution,
    )


def apply_work_item_recovery_state(
    *,
    item: DashboardItem,
    work_item: WorkItemState,
) -> DashboardItem:
    """Apply a shared recovery transition back to its dashboard representation."""
    status = _WORK_ITEM_TO_DASHBOARD_STATUS[work_item.status]
    clear_traceability = work_item.status == "approved" and work_item.publication_retry is None
    linked_change_request = work_item.linked_change_request
    return item.model_copy(
        update={
            "status": status,
            "branch_name": (
                work_item.publication_retry.branch_name
                if work_item.publication_retry is not None
                else (None if clear_traceability else item.branch_name)
            ),
            "change_request_number": (
                None
                if clear_traceability or linked_change_request is None
                else linked_change_request.number
            ),
            "change_request_url": (
                None
                if clear_traceability or linked_change_request is None
                else linked_change_request.web_url
            ),
            "commit_sha": (
                work_item.publication_retry.commit_sha
                if work_item.publication_retry is not None
                else (None if clear_traceability else item.commit_sha)
            ),
            "attempt_number": work_item.attempt_number,
            "retry_count": work_item.attempt_number - 1,
            "retry_eligible": False,
            "retry_block_reason": None,
            "publication_retry": work_item.publication_retry,
            "execution_failure": work_item.execution_failure,
            "recovery_events": list(work_item.recovery_events),
            "resolution": work_item.resolution,
        }
    )


def _change_request_ref(item: DashboardItem) -> ChangeRequestRef | None:
    """Return a linked request only when dashboard traceability is complete."""
    if item.change_request_number is None or item.change_request_url is None:
        return None
    return ChangeRequestRef(
        number=item.change_request_number,
        web_url=item.change_request_url,
    )
