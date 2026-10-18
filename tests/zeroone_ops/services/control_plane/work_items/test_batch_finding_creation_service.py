"""Test creation authorization and explicit uncertain-write outcomes."""

from unittest.mock import patch

import pytest

from zeroone_ops.models.finding_batch_sync import BatchSyncContext
from zeroone_ops.services.control_plane.work_items.batch_finding_creation_service import (
    BatchFindingCreationService,
)
from zeroone_ops.services.intake.finding_batch_promotion_service import FindingBatchPromotionService

from .test_batch_finding_sync_coordinator import NOW, SCOPE, batch_state, finding, policy, seed
from .test_batch_finding_sync_coordinator import harness as harness


def publication(harness, **changes):
    planner = FindingBatchPromotionService()
    run = BatchSyncContext(
        **(dict(repository_scope=SCOPE, policy_state=policy(), run_id="new", now=NOW) | changes)
    )
    unit = planner.plan(
        findings=[finding()],
        records=[],
        policy_state=policy(),
        repository_scope=SCOPE,
        max_active_work_items=10,
    ).selected_new[0]
    return BatchFindingCreationService(harness[2], planner), unit, run


def test_creation_preview_returns_selection_without_identity_write_or_logging(harness, caplog):
    service, unit, run = publication(harness, now=None, persist=False)
    with patch(
        "zeroone_ops.services.control_plane.work_items.batch_finding_creation_service.create_finding_batch_identity",
        side_effect=AssertionError("identity allocated"),
    ):
        outcome = service.publish(unit, run)
    assert outcome.selected_member_count == 1
    assert outcome.record is None
    assert outcome.write_action is None
    assert outcome.warnings == ()
    assert harness[0].create_attempts == 0
    assert not caplog.records


def test_late_dismissal_returns_explicit_suppression(harness, caplog):
    service, unit, run = publication(harness)
    seed(harness, batch_state(status="dismissed"), is_open=False)
    outcome = service.publish(unit, run)
    assert outcome.selected_member_count == 0
    assert outcome.backlog_reason_counts == {"dismissed": 1}
    assert len(outcome.warnings) == 1
    assert harness[0].create_attempts == 0
    assert not caplog.records


@pytest.mark.parametrize("failure", ["create_before", "create_after"])
def test_uncertain_creation_returns_recovery_evidence_without_mutating_counters(harness, failure):
    service, unit, run = publication(harness)
    harness[0].fail = failure
    outcome = service.publish(unit, run)
    assert harness[0].create_attempts == 1
    assert len(outcome.warnings) == 1
    if failure == "create_after":
        assert outcome.record is not None
        assert outcome.write_action == "unchanged"
        assert outcome.selected_member_count == 1
    else:
        assert outcome.record is None
        assert outcome.backlog_reason_counts == {"creation_unconfirmed": 1}


def test_failed_rediscovery_retains_both_warning_causes(harness):
    service, unit, run = publication(harness)
    harness[0].fail = "create_after"
    with patch.object(harness[2], "rediscover_batch", side_effect=RuntimeError("unavailable")):
        outcome = service.publish(unit, run)
    assert len(outcome.warnings) == 2
    assert outcome.backlog_reason_counts == {"ownership_unavailable": 1}
    assert outcome.record is None
    assert harness[0].create_attempts == 1
