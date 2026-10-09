"""Contracts for frozen normalized finding-sync records and inventories."""

from dataclasses import FrozenInstanceError, asdict

import pytest

from zeroone_ops.models.finding_sync import (
    FindingSyncInventory,
    FindingSyncRecord,
    FindingSyncWriteResult,
)
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState


def test_normalized_sync_models_are_frozen_and_retain_authoritative_state():
    state = WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="approved",
        source=WorkItemSourceRef(source="mypy-sarif", source_item_key="finding-1"),
        summary="Fix type",
    )
    record = FindingSyncRecord(
        work_item=state, issue_number=1, issue_url="https://example/1", is_open=True
    )
    inventory = FindingSyncInventory(
        open_work_items=(record,),
        policy_deferred_work_items=(),
        capacity_deferred_work_items=(),
        dismissed_work_items=(),
    )
    result = FindingSyncWriteResult(record=record, action="updated")
    assert inventory.open_work_items[0].work_item is state
    assert result.record is record
    assert asdict(result)["action"] == "updated"
    with pytest.raises(FrozenInstanceError):
        record.is_open = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        inventory.open_work_items = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.action = "created"  # type: ignore[misc]
