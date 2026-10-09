"""Provider-neutral evidence and outcomes for authorized work-item commands."""

from dataclasses import dataclass

from zeroone_ops.models.work_item import WorkItemState


@dataclass(frozen=True)
class AuthorizedWorkItemCommandEvent:
    """Carry one provider-authorized event without native transport models."""

    provider_event_id: int
    request_reference: str
    body: str | None
    actor: str | None
    created_at: str | None


@dataclass(frozen=True)
class WorkItemRecoveryOutcome:
    """Capture final command-processing state and the established counters."""

    work_item: WorkItemState
    matched_command_count: int
    accepted_command_count: int
    rejected_command_count: int
