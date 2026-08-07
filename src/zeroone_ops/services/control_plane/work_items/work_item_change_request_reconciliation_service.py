"""Shared reconciliation of work items against linked change-request state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemState

ClosedUnmergedWorkItemOutcome = Literal["approved", "blocked", "candidate", "completed"]


@dataclass(frozen=True)
class WorkItemChangeRequestReconciliationResult:
    """Summarize one linked change-request reconciliation outcome."""

    action: str
    work_item: WorkItemState
    message: str


class WorkItemChangeRequestReconciliationService:
    """Resolve work-item status from linked provider-neutral change-request state."""

    def reconcile(
        self,
        *,
        work_item: WorkItemState,
        change_request_state: ChangeRequestState,
        closed_unmerged_outcome: ClosedUnmergedWorkItemOutcome,
    ) -> WorkItemChangeRequestReconciliationResult:
        """Return the reconciled work-item state for one linked change request."""
        linked_change_request = ChangeRequestRef(
            number=change_request_state.iid,
            web_url=change_request_state.web_url,
        )
        if change_request_state.state == "opened":
            reconciled = work_item.model_copy(
                update={
                    "status": "in_progress",
                    "linked_change_request": linked_change_request,
                    "claim": None,
                }
            )
            action = "unchanged" if reconciled == work_item else "updated"
            return WorkItemChangeRequestReconciliationResult(
                action=action,
                work_item=reconciled,
                message=f"Change request {change_request_state.iid} is still open.",
            )
        if change_request_state.state == "merged":
            reconciled = work_item.model_copy(
                update={
                    "status": "completed",
                    "linked_change_request": linked_change_request,
                    "claim": None,
                }
            )
            return WorkItemChangeRequestReconciliationResult(
                action="completed",
                work_item=reconciled,
                message=f"Change request {change_request_state.iid} was merged.",
            )
        if change_request_state.state == "closed":
            if closed_unmerged_outcome not in {
                "approved",
                "blocked",
                "candidate",
                "completed",
            }:
                raise ValueError(
                    "closed_unmerged_outcome must be 'approved', 'blocked', 'candidate', "
                    "or 'completed'."
                )
            reconciled = work_item.model_copy(
                update={
                    "status": closed_unmerged_outcome,
                    "linked_change_request": None,
                    "claim": None,
                }
            )
            action = {
                "approved": "reopened",
                "blocked": "blocked",
                "candidate": "demoted",
                "completed": "completed",
            }[closed_unmerged_outcome]
            return WorkItemChangeRequestReconciliationResult(
                action=action,
                work_item=reconciled,
                message=(f"Change request {change_request_state.iid} was closed without merge."),
            )
        return WorkItemChangeRequestReconciliationResult(
            action="unchanged",
            work_item=work_item,
            message=f"Unsupported change-request state: {change_request_state.state}.",
        )
