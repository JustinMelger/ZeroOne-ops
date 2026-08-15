"""Shared lifecycle reconciliation for provider-local work-item stores."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.work_items import (
    work_item_change_request_reconciliation_service as reconciliation_service_module,
)

LOGGER = logging.getLogger(__name__)
_STALE_CLAIM_AGE = timedelta(hours=24)
_NATIVE_ISSUE_TERMINAL_STATUSES = {"completed", "dismissed", "policy_deferred"}


@dataclass(frozen=True)
class WorkItemLifecycleResult:
    """Summarize one bounded provider-local work-item lifecycle pass."""

    recovered_stale_claim_count: int
    demoted_to_candidate_count: int
    completed_count: int
    closed_issue_count: int
    blocked_count: int
    in_progress_count: int
    unchanged_count: int


class WorkItemLifecycleService:
    """Converge work-item state through injected provider-local transport operations."""

    def __init__(
        self,
        *,
        provider_name: str,
        list_open_work_items: Callable[[], list[tuple[int, WorkItemState]]],
        upsert_work_item: Callable[[WorkItemState], int],
        close_work_item_issue: Callable[[int], None],
        get_change_request_state: Callable[[int], ChangeRequestState],
        recoverable_errors: tuple[type[Exception], ...],
        reconciliation_service: (
            reconciliation_service_module.WorkItemChangeRequestReconciliationService | None
        ) = None,
    ) -> None:
        """Initialize shared lifecycle operations for one provider scope."""
        self.provider_name = provider_name
        self.list_open_work_items = list_open_work_items
        self.upsert_work_item = upsert_work_item
        self.close_work_item_issue = close_work_item_issue
        self.get_change_request_state = get_change_request_state
        self.recoverable_errors = recoverable_errors
        self.reconciliation_service = (
            reconciliation_service
            or reconciliation_service_module.WorkItemChangeRequestReconciliationService()
        )

    def reconcile(self, *, now: datetime, persist: bool = True) -> WorkItemLifecycleResult:
        """Reconcile recoverable claims and linked change requests for one provider scope."""
        counts = _LifecycleCounts()
        for issue_number, work_item in self.list_open_work_items():
            updated, action = self._reconcile_work_item(work_item=work_item, now=now)
            if updated is None:
                if persist:
                    self._close_terminal_issue(
                        issue_number=issue_number,
                        work_item=work_item,
                        counts=counts,
                    )
                continue
            if persist and action != "unchanged":
                issue_number = self.upsert_work_item(updated)
            counts.record(action)
            if persist:
                self._close_terminal_issue(
                    issue_number=issue_number,
                    work_item=updated,
                    counts=counts,
                )
        return counts.build()

    def _close_terminal_issue(
        self,
        *,
        issue_number: int,
        work_item: WorkItemState,
        counts: _LifecycleCounts,
    ) -> None:
        """Close a terminal native issue after its machine state has been persisted."""
        if (
            work_item.kind != "remediation"
            or work_item.status not in _NATIVE_ISSUE_TERMINAL_STATUSES
        ):
            return
        try:
            self.close_work_item_issue(issue_number)
        except self.recoverable_errors:
            LOGGER.warning(
                "%s work-item lifecycle could not close terminal native issue",
                self.provider_name,
                extra={
                    "work_item_id": work_item.work_item_id,
                    "issue_number": issue_number,
                    "status": work_item.status,
                },
                exc_info=True,
            )
            return
        counts.record_closed_issue()

    def _reconcile_work_item(
        self,
        *,
        work_item: WorkItemState,
        now: datetime,
    ) -> tuple[WorkItemState | None, str]:
        """Return one safe lifecycle transition, when the record needs attention."""
        if work_item.kind != "remediation":
            return None, "unchanged"
        if work_item.linked_change_request is None:
            if self._is_stale_unlinked_claim(work_item=work_item, now=now):
                LOGGER.info(
                    "recovered stale unlinked %s remediation claim",
                    self.provider_name,
                    extra={"work_item_id": work_item.work_item_id},
                )
                return (
                    work_item.model_copy(update={"status": "approved", "claim": None}),
                    "recovered_stale_claim",
                )
            return None, "unchanged"
        if work_item.status not in {"approved", "in_progress", "blocked"}:
            return None, "unchanged"
        return self._reconcile_linked_change_request(work_item=work_item)

    def _reconcile_linked_change_request(
        self, *, work_item: WorkItemState
    ) -> tuple[WorkItemState, str]:
        """Resolve one linked change request, retaining links when state is uncertain."""
        linked_change_request = work_item.linked_change_request
        if linked_change_request is None:
            raise ValueError("Linked work-item reconciliation requires a change request.")
        try:
            change_request_state = self.get_change_request_state(linked_change_request.number)
        except self.recoverable_errors:
            LOGGER.warning(
                "%s work-item lifecycle could not load linked change request",
                self.provider_name,
                extra={
                    "work_item_id": work_item.work_item_id,
                    "change_request_number": linked_change_request.number,
                },
                exc_info=True,
            )
            return self._blocked_with_link(work_item), "blocked"
        if change_request_state.iid != linked_change_request.number:
            LOGGER.warning(
                "%s work-item lifecycle received mismatched change-request metadata",
                self.provider_name,
                extra={
                    "work_item_id": work_item.work_item_id,
                    "linked_change_request_number": linked_change_request.number,
                    "received_change_request_number": change_request_state.iid,
                },
            )
            return self._blocked_with_link(work_item), "blocked"
        if change_request_state.state == "closed":
            if work_item.status == "blocked":
                return work_item, "unchanged"
            return self._blocked_with_link(work_item), "blocked"
        if change_request_state.state not in {"opened", "merged"}:
            LOGGER.warning(
                "%s work-item lifecycle received unsupported change-request state",
                self.provider_name,
                extra={
                    "work_item_id": work_item.work_item_id,
                    "change_request_number": linked_change_request.number,
                    "change_request_state": change_request_state.state,
                },
            )
            return self._blocked_with_link(work_item), "blocked"
        reconciliation = self.reconciliation_service.reconcile(
            work_item=work_item,
            change_request_state=change_request_state,
            closed_unmerged_outcome="blocked",
        )
        return reconciliation.work_item, reconciliation.action

    def _is_stale_unlinked_claim(self, *, work_item: WorkItemState, now: datetime) -> bool:
        """Return whether an unlinked in-progress claim exceeded the recovery window."""
        if work_item.status != "in_progress" or work_item.claim is None:
            return False
        claimed_at = work_item.claim.claimed_at
        if claimed_at.tzinfo is None:
            LOGGER.warning(
                "%s work-item lifecycle skipped stale recovery for naive claim timestamp",
                self.provider_name,
                extra={"work_item_id": work_item.work_item_id},
            )
            return False
        return now.astimezone(UTC) - claimed_at.astimezone(UTC) >= _STALE_CLAIM_AGE

    @staticmethod
    def _blocked_with_link(work_item: WorkItemState) -> WorkItemState:
        """Block uncertain reconciliation while retaining linked change-request traceability."""
        return work_item.model_copy(update={"status": "blocked", "claim": None})


@dataclass
class _LifecycleCounts:
    """Accumulate lifecycle actions without exposing mutable runner state."""

    recovered_stale_claim_count: int = 0
    demoted_to_candidate_count: int = 0
    completed_count: int = 0
    closed_issue_count: int = 0
    blocked_count: int = 0
    in_progress_count: int = 0
    unchanged_count: int = 0

    def record(self, action: str) -> None:
        """Record one provider-local lifecycle action."""
        if action == "recovered_stale_claim":
            self.recovered_stale_claim_count += 1
        elif action == "demoted":
            self.demoted_to_candidate_count += 1
        elif action == "completed":
            self.completed_count += 1
        elif action == "blocked":
            self.blocked_count += 1
        elif action == "updated":
            self.in_progress_count += 1
        else:
            self.unchanged_count += 1

    def record_closed_issue(self) -> None:
        """Record a terminal native issue closure."""
        self.closed_issue_count += 1

    def build(self) -> WorkItemLifecycleResult:
        """Return an immutable lifecycle summary."""
        return WorkItemLifecycleResult(
            recovered_stale_claim_count=self.recovered_stale_claim_count,
            demoted_to_candidate_count=self.demoted_to_candidate_count,
            completed_count=self.completed_count,
            closed_issue_count=self.closed_issue_count,
            blocked_count=self.blocked_count,
            in_progress_count=self.in_progress_count,
            unchanged_count=self.unchanged_count,
        )
