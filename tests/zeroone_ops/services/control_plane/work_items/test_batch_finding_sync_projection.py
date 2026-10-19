"""Test guarded projection outcomes independently of aggregate reporting."""

from zeroone_ops.services.control_plane.work_items.batch_finding_sync_projection import (
    BatchFindingSyncProjection,
)

from .test_batch_finding_sync_coordinator import SCOPE, batch_state, seed
from .test_batch_finding_sync_coordinator import harness as harness


def test_projection_returns_actual_write_and_previous_status(harness):
    original = batch_state()
    seed(harness, original)
    existing = harness[2].read_work_item(repository_scope=SCOPE, issue_number=1)
    desired = original.model_copy(update={"status": "approved"})
    outcome = BatchFindingSyncProjection(harness[2]).project(SCOPE, existing, desired, persist=True)
    assert outcome.previous_status == "candidate"
    assert outcome.record.work_item.status == "approved"
    assert outcome.write_action == "updated"
    assert outcome.warnings == ()
    assert existing.work_item.status == "candidate"


def test_partial_projection_failure_is_not_reported_as_a_completed_transition(harness, caplog):
    original = batch_state()
    seed(harness, original)
    existing = harness[2].read_work_item(repository_scope=SCOPE, issue_number=1)
    desired = original.model_copy(
        update={"status": "completed", "resolution": "no_longer_detected"}
    )
    harness[0].fail = "close"
    outcome = BatchFindingSyncProjection(harness[2]).project(SCOPE, existing, desired, persist=True)
    assert outcome.previous_status == "candidate"
    assert outcome.record is None
    assert outcome.write_action is None
    assert len(outcome.warnings) == 1
    assert harness[0].open[1]
    assert not caplog.records
