"""The review linkage record is frozen, non-persisted, and provider-neutral."""

from dataclasses import FrozenInstanceError, fields

import pytest

from zeroone_ops.models.review_linkage import LinkedReviewWorkItem
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState


def test_linkage_retains_original_state_without_native_issue_or_schema_fields():
    state = WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="candidate",
        summary="Fix",
        source=WorkItemSourceRef(source="ruff", source_item_key="a"),
    )
    record = LinkedReviewWorkItem(state, "https://example/issues/1")

    assert record.work_item is state
    assert [field.name for field in fields(record)] == ["work_item", "issue_url"]
    with pytest.raises(FrozenInstanceError):
        record.issue_url = "https://other.example/issues/1"
