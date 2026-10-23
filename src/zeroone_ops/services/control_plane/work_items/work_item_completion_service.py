"""Revalidate absence-driven remediation completion at the authoritative read."""

from collections.abc import Callable

from zeroone_ops.models.remediation import RemediationCompletionRequest, RemediationCompletionResult
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.work_items.work_item_state_merge import (
    merge_remediation_work_item_state,
)


def complete_absent_batch(
    *,
    existing: WorkItemState,
    request: RemediationCompletionRequest,
    persist_work_item: Callable[[WorkItemState], WorkItemState],
) -> RemediationCompletionResult:
    """Complete only unchanged execution authority whose members remain currently absent.

    Providers supply their existing authoritative lookup and direct update. A
    refused transition performs no write; this guard is not an atomic reservation.
    """
    incoming = request.work_item
    if (
        existing.kind != "remediation"
        or existing.work_item_id != incoming.work_item_id
        or existing.identity_key != incoming.identity_key
        or existing.attempt_number != incoming.attempt_number
        or existing.batch is None
        or incoming.batch is None
        or existing.batch.group != incoming.batch.group
        or existing.batch.members != incoming.batch.members
        or incoming.status != "completed"
        or incoming.resolution != "no_longer_detected"
        or existing.linked_change_request is not None
        or existing.publication_retry is not None
        or existing.review_revision_request is not None
        or not all(
            observation.last_confirmed_presence == "absent" and observation.freshness == "current"
            for observation in existing.batch.observations
        )
    ):
        return RemediationCompletionResult(
            False, "Batch completion was not applied: authoritative absence or ownership changed."
        )

    if existing.status == "completed" and existing.resolution == "no_longer_detected":
        return RemediationCompletionResult(True, "Batch absence completion is already recorded.")

    if (
        existing.status not in {"approved", "in_progress"}
        or existing.claim != request.expected_claim
    ):
        return RemediationCompletionResult(
            False, "Batch completion was not applied: authoritative status or claim changed."
        )

    persisted = persist_work_item(merge_remediation_work_item_state(existing, incoming))
    if persisted.status != "completed" or persisted.resolution != "no_longer_detected":
        return RemediationCompletionResult(False, "Batch completion could not be confirmed.")

    return RemediationCompletionResult(True, "All original batch members are no longer detected.")
