"""Reconcile authoritative GitHub work items with remediation lifecycle state."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.services.control_plane.work_items.github_work_item_reconciliation_service import (
    ClosedUnmergedWorkItemOutcome,
    GitHubWorkItemReconciliationService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)

LOGGER = logging.getLogger(__name__)
_STALE_CLAIM_AGE = timedelta(hours=24)


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
    reopened_count: int
    demoted_to_candidate_count: int
    completed_count: int
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
        active_source_keys: set[tuple[str, str]],
        promotable_source_keys: set[tuple[str, str]],
        managed_source_ids: set[str],
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
                active_source_keys=active_source_keys,
                promotable_source_keys=promotable_source_keys,
                managed_source_ids=managed_source_ids,
                now=now,
            )
            if updated is None:
                continue
            if persist:
                self.work_item_service.upsert_work_item(
                    repository_id=repository_id,
                    work_item=updated,
                )
            counts.record(action)
        return counts.build()

    def _reconcile_work_item(
        self,
        *,
        repository_id: str,
        work_item: WorkItemState,
        active_source_keys: set[tuple[str, str]],
        promotable_source_keys: set[tuple[str, str]],
        managed_source_ids: set[str],
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
            active_source_keys=active_source_keys,
            promotable_source_keys=promotable_source_keys,
            managed_source_ids=managed_source_ids,
        )

    def _reconcile_linked_change_request(
        self,
        *,
        repository_id: str,
        work_item: WorkItemState,
        active_source_keys: set[tuple[str, str]],
        promotable_source_keys: set[tuple[str, str]],
        managed_source_ids: set[str],
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
            closed_unmerged_outcome = self._closed_unmerged_outcome(
                work_item=work_item,
                active_source_keys=active_source_keys,
                promotable_source_keys=promotable_source_keys,
                managed_source_ids=managed_source_ids,
            )
            if closed_unmerged_outcome is None:
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
        else:
            closed_unmerged_outcome = "blocked"
        reconciliation = self.reconciliation_service.reconcile(
            work_item=work_item,
            change_request_state=change_request_state,
            closed_unmerged_outcome=closed_unmerged_outcome,
        )
        return reconciliation.work_item, reconciliation.action

    def _closed_unmerged_outcome(
        self,
        *,
        work_item: WorkItemState,
        active_source_keys: set[tuple[str, str]],
        promotable_source_keys: set[tuple[str, str]],
        managed_source_ids: set[str],
    ) -> ClosedUnmergedWorkItemOutcome | None:
        """Return a safe closed-PR transition from the current source inventory."""
        source_id = work_item.source.source
        if source_id not in managed_source_ids:
            LOGGER.warning(
                "GitHub work-item lifecycle cannot reconcile closed pull request from an "
                "incomplete source inventory",
                extra={"work_item_id": work_item.work_item_id, "source_id": source_id},
            )
            return None
        source_key = (source_id, work_item.source.source_item_key)
        if source_key not in active_source_keys:
            return "completed"
        if source_key not in promotable_source_keys:
            return "candidate"
        return "approved"

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
    reopened_count: int = 0
    demoted_to_candidate_count: int = 0
    completed_count: int = 0
    blocked_count: int = 0
    in_progress_count: int = 0
    unchanged_count: int = 0

    def record(self, action: str) -> None:
        """Record one provider-local lifecycle action."""
        if action == "recovered_stale_claim":
            self.recovered_stale_claim_count += 1
        elif action == "reopened":
            self.reopened_count += 1
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

    def build(self) -> GitHubWorkItemLifecycleResult:
        """Return an immutable lifecycle summary."""
        return GitHubWorkItemLifecycleResult(
            recovered_stale_claim_count=self.recovered_stale_claim_count,
            reopened_count=self.reopened_count,
            demoted_to_candidate_count=self.demoted_to_candidate_count,
            completed_count=self.completed_count,
            blocked_count=self.blocked_count,
            in_progress_count=self.in_progress_count,
            unchanged_count=self.unchanged_count,
        )
