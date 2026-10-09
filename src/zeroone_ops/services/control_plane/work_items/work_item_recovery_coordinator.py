"""Process already-authorized work-item events independently of providers."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.models.work_item_recovery import (
    AuthorizedWorkItemCommandEvent,
    WorkItemRecoveryOutcome,
)
from zeroone_ops.services.control_plane.work_items.work_item_recovery_command_parser import (
    WorkItemRecoveryCommandParser,
)
from zeroone_ops.services.remediation.recovery.work_item_command_decision_service import (
    WorkItemCommandDecisionService,
)


class WorkItemRecoveryCoordinator:
    """Sequence shared command decisions without discovery or authorization."""

    def __init__(
        self,
        *,
        command_parser: WorkItemRecoveryCommandParser,
        command_decision_service: WorkItemCommandDecisionService,
    ) -> None:
        """Retain the existing parser and decision service without side effects."""
        self.command_parser = command_parser
        self.command_decision_service = command_decision_service

    def process(
        self,
        *,
        work_item: WorkItemState,
        events: Sequence[AuthorizedWorkItemCommandEvent],
        policy_eligible: bool,
        persist: bool,
        persist_work_item: Callable[[WorkItemState], WorkItemState],
    ) -> WorkItemRecoveryOutcome:
        """Apply ordered commands, using each authoritative persistence response.

        Args:
            work_item: Initial authoritative state supplied by provider discovery.
            events: Only events already authorized by the provider wrapper.
            policy_eligible: Existing eligibility for a fresh remediation attempt.
            persist: Whether to write accepted transitions or simulate them.
            persist_work_item: Direct provider update returning authoritative state.

        Returns:
            Final state and matched, accepted, and rejected command counts.
        """
        current = work_item
        processed_references = {event.request_reference for event in current.recovery_events}
        if current.review_revision_request is not None:
            processed_references.add(current.review_revision_request.request_reference)
        if current.last_revision_command is not None:
            processed_references.add(current.last_revision_command.request_reference)
        matched_count = accepted_count = rejected_count = 0
        for event in sorted(events, key=_event_sort_key):
            command = self.command_parser.parse(event.body)
            if not command.matched_prefix:
                continue
            matched_count += 1
            reference = event.request_reference
            if command.action is None or reference in processed_references:
                rejected_count += command.action is None
                continue
            occurred_at = _parse_event_timestamp(event.created_at)
            if (
                occurred_at is None
                or _is_older_than_latest_event(current, occurred_at)
                or event.actor is None
            ):
                rejected_count += 1
                continue
            decision = self.command_decision_service.decide(
                work_item=current,
                action=command.action,
                actor=event.actor,
                request_reference=reference,
                occurred_at=occurred_at,
                policy_eligible=policy_eligible,
            )
            if not decision.accepted:
                rejected_count += 1
                continue
            current = persist_work_item(decision.work_item) if persist else decision.work_item
            processed_references.add(reference)
            accepted_count += 1
        return WorkItemRecoveryOutcome(
            work_item=current,
            matched_command_count=matched_count,
            accepted_command_count=accepted_count,
            rejected_command_count=rejected_count,
        )


def _event_sort_key(event: AuthorizedWorkItemCommandEvent) -> tuple[bool, datetime, int]:
    """Sort invalid timestamps last without converting through the host timezone."""
    timestamp = _parse_event_timestamp(event.created_at)
    return (
        timestamp is None,
        timestamp if timestamp is not None else datetime.min.replace(tzinfo=UTC),
        event.provider_event_id,
    )


def _parse_event_timestamp(value: str | None) -> datetime | None:
    """Parse timestamps only when they contain an explicit timezone."""
    if value is None:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None else None


def _is_older_than_latest_event(work_item: WorkItemState, occurred_at: datetime) -> bool:
    """Reject events at or before the latest accepted recovery transition."""
    return bool(
        work_item.recovery_events and occurred_at <= work_item.recovery_events[-1].occurred_at
    )
