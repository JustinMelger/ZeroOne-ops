"""Merge authoritative work-item state without provider access."""

from zeroone_ops.models.work_item import WorkItemState

_PRESERVED_OPTIONAL_FIELDS = (
    "linked_change_request",
    "projected_review",
    "publication_retry",
    "execution_failure",
    "policy_deferral",
    "capacity_deferral",
    "resolution",
    "last_revision_command",
    "review_action_required_at",
)


def merge_authoritative_work_item_state(
    existing: WorkItemState, incoming: WorkItemState
) -> WorkItemState:
    """Retain authoritative identity and selected fields omitted by an update.

    Explicit values, including None and empty histories, take precedence. Fields
    outside the existing preservation contract follow the incoming state.

    Args:
        existing: Parsed state from the matched authoritative issue.
        incoming: Proposed state, retaining its supplied-field information.

    Returns:
        A merged copy without modifying either input.
    """
    update: dict[str, object] = {"work_item_id": existing.work_item_id}
    for field_name in _PRESERVED_OPTIONAL_FIELDS:
        existing_value = getattr(existing, field_name)
        if field_name not in incoming.model_fields_set and existing_value is not None:
            update[field_name] = existing_value
    for field_name in ("attempt_number", "recovery_events"):
        if field_name not in incoming.model_fields_set:
            update[field_name] = getattr(existing, field_name)
    return incoming.model_copy(update=update)
