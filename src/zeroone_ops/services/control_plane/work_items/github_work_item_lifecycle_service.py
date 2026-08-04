"""Reconcile authoritative GitHub work items with remediation lifecycle state."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.services.control_plane.work_items.github_work_item_reconciliation_service import (
    GitHubWorkItemReconciliationService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)

LOGGER = logging.getLogger(__name__)
_STALE_CLAIM_AGE = timedelta(hours=24)
_NATIVE_ISSUE_TERMINAL_STATUSES = {"completed", "dismissed"}


class GitHubChangeRequestStateClient(Protocol):
    """Fetch provider-local state for one linked GitHub pull request."""

    def get_change_request_state(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> ChangeRequestState:
        """Return current state for one GitHub pull request."""


@dataclass(frozen=True)
class GitHubWorkItemLifecycleResult:
    """Summarize one bounded GitHub work-item lifecycle pass."""

    recovered_stale_claim_count: int
    demoted_to_candidate_count: int
    completed_count: int
    closed_issue_count: int
    blocked_count: int
    in_progress_count: int
    unchanged_count: int


class GitHubWorkItemLifecycleService:
    """Converge GitHub work-item state without changing source-discovery ownership."""

    def __init__(
        self,
        *,
        work_item_service: GitHubWorkItemService,
        change_request_client: GitHubChangeRequestStateClient,
        reconciliation_service: GitHubWorkItemReconciliationService | None = None,
    ) -> None:
        """Initialize the GitHub lifecycle service."""
        self.work_item_service = work_item_service
        self.change_request_client = change_request_client
        self.reconciliation_service = (
            reconciliation_service or GitHubWorkItemReconciliationService()
        )

    def reconcile(
        self,
        *,
        repository_id: str,
        now: datetime,
        persist: bool = True,
    ) -> GitHubWorkItemLifecycleResult:
        """Reconcile recoverable claims and linked pull requests for one repository."""
        counts = _LifecycleCounts()
        for result in self.work_item_service.list_open_work_items(repository_id=repository_id):
            work_item = result.work_item
            updated, action = self._reconcile_work_item(
                repository_id=repository_id,
                work_item=work_item,
                now=now,
            )
            if updated is None:
                if persist:
                    self._close_terminal_issue(
                        repository_id=repository_id,
                        issue_number=result.issue.number,
                        work_item=work_item,
                        counts=counts,
                    )
                continue
            issue_number = result.issue.number
            if persist and action != "unchanged":
                upsert_result = self.work_item_service.upsert_work_item(
                    repository_id=repository_id,
                    work_item=updated,
                )
                issue_number = upsert_result.issue.number
            counts.record(action)
            if persist:
                self._close_terminal_issue(
                    repository_id=repository_id,
                    issue_number=issue_number,
                    work_item=updated,
                    counts=counts,
                )
        return counts.build()

    def _close_terminal_issue(
        self,
        *,
        repository_id: str,
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
            self.work_item_service.close_work_item_issue(
                repository_id=repository_id,
                issue_number=issue_number,
            )
        except (GitHubClientError, httpx.HTTPError):
            LOGGER.warning(
                "GitHub work-item lifecycle could not close terminal native issue",
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
        repository_id: str,
        work_item: WorkItemState,
        now: datetime,
    ) -> tuple[WorkItemState | None, str]:
        """Return one safe lifecycle transition, when the record needs attention."""
        if work_item.kind != "remediation":
            return None, "unchanged"
        if work_item.linked_change_request is None:
            if self._is_stale_unlinked_claim(work_item=work_item, now=now):
                LOGGER.info(
                    "recovered stale unlinked GitHub remediation claim",
                    extra={"work_item_id": work_item.work_item_id},
                )
                return (
                    work_item.model_copy(update={"status": "approved", "claim": None}),
                    "recovered_stale_claim",
                )
            return None, "unchanged"
        if work_item.status not in {"approved", "in_progress", "blocked"}:
            return None, "unchanged"
        return self._reconcile_linked_change_request(
            repository_id=repository_id,
            work_item=work_item,
        )

    def _reconcile_linked_change_request(
        self,
        *,
        repository_id: str,
        work_item: WorkItemState,
    ) -> tuple[WorkItemState, str]:
        """Resolve one linked pull request, preserving links when state is uncertain."""
        linked_change_request = work_item.linked_change_request
        if linked_change_request is None:
            raise ValueError("Linked work-item reconciliation requires a change request.")
        try:
            change_request_state = self.change_request_client.get_change_request_state(
                repository_id=repository_id,
                change_request_number=linked_change_request.number,
            )
        except GitHubClientError:
            LOGGER.warning(
                "GitHub work-item lifecycle could not load linked pull request",
                extra={
                    "work_item_id": work_item.work_item_id,
                    "change_request_number": linked_change_request.number,
                },
                exc_info=True,
            )
            return self._blocked_with_link(work_item), "blocked"
        if change_request_state.iid != linked_change_request.number:
            LOGGER.warning(
                "GitHub work-item lifecycle received mismatched pull-request metadata",
                extra={
                    "work_item_id": work_item.work_item_id,
                    "linked_change_request_number": linked_change_request.number,
                    "received_change_request_number": change_request_state.iid,
                },
            )
            return self._blocked_with_link(work_item), "blocked"
        if change_request_state.state == "closed":
            # A closed PR is an operator-visible decision, not an invitation to retry.
            if work_item.status == "blocked":
                return work_item, "unchanged"
            return self._blocked_with_link(work_item), "blocked"
        elif change_request_state.state not in {"opened", "merged"}:
            LOGGER.warning(
                "GitHub work-item lifecycle received unsupported pull-request state",
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
        """Return whether an unlinked in-progress claim has exceeded the recovery window."""
        if work_item.status != "in_progress" or work_item.claim is None:
            return False
        claimed_at = work_item.claim.claimed_at
        if claimed_at.tzinfo is None:
            LOGGER.warning(
                "GitHub work-item lifecycle skipped stale recovery for naive claim timestamp",
                extra={"work_item_id": work_item.work_item_id},
            )
            return False
        return now.astimezone(UTC) - claimed_at.astimezone(UTC) >= _STALE_CLAIM_AGE

    def _blocked_with_link(self, work_item: WorkItemState) -> WorkItemState:
        """Block uncertain reconciliation while retaining linked pull-request traceability."""
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
        """Record a terminal native GitHub issue closure."""
        self.closed_issue_count += 1

    def build(self) -> GitHubWorkItemLifecycleResult:
        """Return an immutable lifecycle summary."""
        return GitHubWorkItemLifecycleResult(
            recovered_stale_claim_count=self.recovered_stale_claim_count,
            demoted_to_candidate_count=self.demoted_to_candidate_count,
            completed_count=self.completed_count,
            closed_issue_count=self.closed_issue_count,
            blocked_count=self.blocked_count,
            in_progress_count=self.in_progress_count,
            unchanged_count=self.unchanged_count,
        )
