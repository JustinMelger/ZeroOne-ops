"""Keep work-item transition accounting separate from member and backlog units."""

from dataclasses import replace

from zeroone_ops.models.finding_batch_promotion import (
    FindingBatchPromotionPlan,
    FindingBatchPromotionUnit,
)
from zeroone_ops.models.finding_batch_sync import BatchCreationOutcome, BatchProjectionOutcome
from zeroone_ops.models.finding_sync import FindingSyncRecord
from zeroone_ops.services.control_plane.work_items.batch_finding_sync_report import (
    BatchFindingSyncReport,
)

from .test_batch_finding_sync_coordinator import SCOPE, batch_state, finding, policy


def report():
    return BatchFindingSyncReport(
        FindingBatchPromotionPlan(
            selected_new=(),
            selected_existing=(),
            decisions=(),
            conflicts=(),
            active_work_item_count=0,
        ),
        (),
        SCOPE,
    )


def test_report_aggregates_explicit_projection_and_creation_outcomes():
    state = batch_state(members=[finding("a"), finding("b")])
    existing = FindingSyncRecord(state, 1, "https://example/issues/1", True)
    selected = FindingBatchPromotionUnit(state.batch.group, (finding("a"), finding("b")), existing)
    projection = BatchProjectionOutcome(
        "candidate",
        replace(existing, work_item=state.model_copy(update={"status": "approved"})),
        "updated",
    )
    summary = report()
    summary.record_projection(projection, selected)
    summary.record_creation(BatchCreationOutcome(selected_member_count=3))

    result = summary.build([], policy())
    assert result.promoted_count == 2
    assert result.selected_member_count == 5
    assert result.updated_count == 1
    assert result.created_count == 0
    assert result.projection_warning_count == 0
    assert projection.record.work_item.status == "approved"


def test_report_counts_failed_member_scope_and_warning_causes_without_altering_outcomes():
    state = batch_state()
    selected = FindingBatchPromotionUnit(state.batch.group, (finding(),))
    summary = report()
    summary.record_projection(
        BatchProjectionOutcome("candidate", warnings=("projection failed",)), selected
    )
    creation = BatchCreationOutcome(
        backlog_reason_counts={"ownership_unavailable": 2}, warnings=("uncertain", "lookup failed")
    )
    summary.record_creation(creation)

    result = summary.build([], policy())
    assert result.backlog_reason_counts == {"projection_failed": 1, "ownership_unavailable": 2}
    assert result.backlog_only_count == 3
    assert result.projection_warning_count == 3
    assert result.promoted_count == 0
    assert creation.backlog_reason_counts == {"ownership_unavailable": 2}
