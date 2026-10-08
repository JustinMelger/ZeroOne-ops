"""Contracts for normalized remediation intake records and outcomes."""

from dataclasses import FrozenInstanceError

import pytest

from zeroone_ops.models.remediation_intake import RemediationIntakeOutcome, RemediationIntakeRecord
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState


def test_intake_record_defaults_and_frozen_fields() -> None:
    work_item = WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="approved",
        source=WorkItemSourceRef(source="sonarqube", source_item_key="AX123"),
        summary="Fix error",
    )
    record = RemediationIntakeRecord(
        work_item=work_item,
        issue_number=11,
        issue_url="https://example/issues/11",
    )

    assert record.work_item is work_item
    assert record.created_at is None
    with pytest.raises(FrozenInstanceError):
        record.issue_number = 12  # type: ignore[misc]


def test_empty_intake_outcome_is_frozen() -> None:
    outcome = RemediationIntakeOutcome(selected_record=None, selected_target=None, item_count=3)

    assert outcome.selected_record is None
    assert outcome.selected_target is None
    assert outcome.item_count == 3
    with pytest.raises(FrozenInstanceError):
        outcome.item_count = 4  # type: ignore[misc]
