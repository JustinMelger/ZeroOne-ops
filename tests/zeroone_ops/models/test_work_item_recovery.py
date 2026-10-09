"""Contracts for normalized authorized events and processing outcomes."""

from dataclasses import FrozenInstanceError, asdict

import pytest

from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.models.work_item_recovery import (
    AuthorizedWorkItemCommandEvent,
    WorkItemRecoveryOutcome,
)


def test_authorized_event_preserves_optional_evidence_and_is_frozen():
    event = AuthorizedWorkItemCommandEvent(21, "github-comment-21", None, None, None)
    assert asdict(event) == {
        "provider_event_id": 21,
        "request_reference": "github-comment-21",
        "body": None,
        "actor": None,
        "created_at": None,
    }
    with pytest.raises(FrozenInstanceError):
        event.body = "changed"


def test_processing_outcome_retains_state_and_counters_and_is_frozen():
    state = WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="blocked",
        source=WorkItemSourceRef(
            source="sonarqube", source_item_key="AX123", repository_scope="org/repo"
        ),
        summary="Remediate selected finding",
        severity="high",
    )
    result = WorkItemRecoveryOutcome(state, 3, 1, 1)
    assert result.work_item is state
    assert result.matched_command_count == 3
    assert result.accepted_command_count == result.rejected_command_count == 1
    assert asdict(result)["work_item"] == state
    with pytest.raises(FrozenInstanceError):
        result.accepted_command_count = 2
