"""Provider-local reconciliation of GitHub work items against linked PR state."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemState


@dataclass(frozen=True)
class GitHubWorkItemReconciliationResult:
    """Summarize one linked-PR reconciliation outcome for a GitHub work item."""

    action: str
    work_item: WorkItemState
    message: str


class GitHubWorkItemReconciliationService:
    """Resolve work-item status from linked GitHub pull-request state."""

    def reconcile(
        self,
        *,
        work_item: WorkItemState,
        change_request_state: ChangeRequestState,
    ) -> GitHubWorkItemReconciliationResult:
        """Return the reconciled work-item state for one linked pull request."""
        linked_change_request = ChangeRequestRef(
            number=change_request_state.iid,
            web_url=change_request_state.web_url,
        )
        if change_request_state.state == "opened":
            reconciled = work_item.model_copy(
                update={
                    "status": "in_progress",
                    "linked_change_request": linked_change_request,
                }
            )
            action = "unchanged" if reconciled == work_item else "updated"
            return GitHubWorkItemReconciliationResult(
                action=action,
                work_item=reconciled,
                message=f"Pull request {change_request_state.iid} is still open.",
            )
        if change_request_state.state == "merged":
            reconciled = work_item.model_copy(
                update={
                    "status": "completed",
                    "linked_change_request": linked_change_request,
                }
            )
            return GitHubWorkItemReconciliationResult(
                action="completed",
                work_item=reconciled,
                message=f"Pull request {change_request_state.iid} was merged.",
            )
        if change_request_state.state == "closed":
            reconciled = work_item.model_copy(
                update={
                    "status": "approved",
                    "linked_change_request": linked_change_request,
                }
            )
            return GitHubWorkItemReconciliationResult(
                action="reopened",
                work_item=reconciled,
                message=f"Pull request {change_request_state.iid} was closed without merge.",
            )
        return GitHubWorkItemReconciliationResult(
            action="unchanged",
            work_item=work_item,
            message=f"Unsupported pull request state: {change_request_state.state}.",
        )
