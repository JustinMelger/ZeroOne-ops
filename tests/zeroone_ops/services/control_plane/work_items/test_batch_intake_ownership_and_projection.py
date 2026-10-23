"""Protect batch ownership and sync evidence through both issue adapters."""

from unittest.mock import Mock

import pytest

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.finding_batch import BatchSelectionFailure
from zeroone_ops.models.remediation_intake import RemediationIntakeRecord
from zeroone_ops.services.control_plane.work_items.remediation_intake_coordinator import (
    RemediationIntakeCoordinator,
)
from zeroone_ops.services.control_plane.work_items.remediation_work_item_selection_service import (
    is_internal_remediation_execution_eligible,
)
from zeroone_ops.services.control_plane.work_items.work_item_state_merge import (
    merge_authoritative_work_item_state,
    merge_remediation_work_item_state,
)
from zeroone_ops.services.remediation.batch_execution_scope_service import (
    BatchExecutionScopeService,
)
from zeroone_ops.services.remediation.control_plane import (
    GitHubRemediationControlPlane,
    GitLabRemediationControlPlane,
)
from zeroone_ops.services.remediation.remediation_execution_adapter import (
    control_plane_work_item_to_execution_target,
)

from .test_batch_finding_sync_coordinator import (
    NOW,
    SCOPE,
    batch_state,
    finding,
    policy,
    seed,
    stored,
    sync,
)
from .test_batch_finding_sync_coordinator import harness as harness


@pytest.mark.parametrize("persist", [False, True])
@pytest.mark.parametrize("overlapping_members", [False, True])
def test_reopened_duplicate_batches_are_withheld_without_claim_or_clock(
    harness, persist, overlapping_members, caplog
):
    client, _, storage = harness
    original = batch_state(status="approved")
    seed(harness, original, is_open=False)
    seed(
        harness,
        batch_state(
            status="approved", members=[finding("a" if overlapping_members else "replacement")]
        ),
    )
    client.open[1] = True
    records = [
        RemediationIntakeRecord(record.work_item, record.issue_number, record.issue_url)
        for record in storage.load_inventory(repository_scope=SCOPE).open_work_items
    ]
    clock = Mock(return_value=NOW)
    write = Mock()

    result = RemediationIntakeCoordinator(
        clock=clock,
        eligibility=is_internal_remediation_execution_eligible,
        batch_policy=policy(),
    ).select_and_claim(records=records, persist_work_item=write, persist=persist)

    assert result.selected_record is None
    assert result.selected_target is None
    assert result.item_count == 2
    clock.assert_not_called()
    write.assert_not_called()
    assert "Withheld ambiguous batch intake" in caplog.text
    assert stored(harness, 1) == original


def test_ambiguous_group_does_not_prevent_unrelated_batch_selection(harness):
    _, _, storage = harness
    seed(harness, batch_state(status="approved"))
    seed(harness, batch_state(status="approved"))
    seed(harness, batch_state(status="approved", members=[finding("other", path="src/other.py")]))
    records = [
        RemediationIntakeRecord(record.work_item, record.issue_number, record.issue_url)
        for record in storage.load_inventory(repository_scope=SCOPE).open_work_items
    ]
    result = RemediationIntakeCoordinator(
        clock=Mock(),
        eligibility=is_internal_remediation_execution_eligible,
        batch_policy=policy(),
    ).select_and_claim(records=records, persist_work_item=Mock(), persist=False)

    assert result.selected_record.issue_number == 3
    assert result.selected_target.batch_attempt.members[0].finding_id == "other"


@pytest.mark.parametrize("projection", ["publish_started", "blocked", "linked"])
@pytest.mark.parametrize("source_available", [False, True])
def test_execution_projection_preserves_newer_sync_observations_and_attempt(
    harness, projection, source_available
):
    client, service, _ = harness
    original = batch_state(status="in_progress")
    attempt = BatchExecutionScopeService().resolve(original, policy(), run_id="execution").attempt
    original = original.model_copy(update={"batch_attempt": attempt})
    seed(harness, original)
    target = control_plane_work_item_to_execution_target(original)

    sync(harness, [], managed_source_ids={"ruff-sarif"} if source_available else set())
    refreshed = stored(harness)
    assert refreshed.batch.observations[0].last_confirmed_presence == (
        "absent" if source_available else "detected"
    )
    assert refreshed.batch.observations[0].freshness == (
        "current" if source_available else "unknown"
    )
    control_plane = (
        GitHubRemediationControlPlane(work_item_service=service, repository_id=SCOPE)
        if client.provider == "github"
        else GitLabRemediationControlPlane(work_item_service=service, project_id=SCOPE)
    )

    if projection == "publish_started":
        control_plane.mark_publish_started(selected_issue=target)
    elif projection == "blocked":
        control_plane.mark_execution_blocked(selected_issue=target, existing_work_item=original)
    else:
        control_plane.sync_change_request_link(
            selected_issue=target,
            published_change_request=ChangeRequestInfo(
                iid=9, web_url="https://example/requests/9", title="Remove imports"
            ),
            existing_work_item=original,
        )

    persisted = stored(harness)
    assert persisted.batch == refreshed.batch
    assert persisted.batch_attempt == attempt
    assert persisted.work_item_id == original.work_item_id
    if projection == "blocked":
        assert persisted.status == "blocked"
    if projection == "linked":
        assert persisted.linked_change_request.number == 9


def test_execution_merge_preserves_selection_evidence_without_changing_sync_merge_contract():
    original = batch_state(status="in_progress")
    latest_batch = original.batch.model_copy(
        update={
            "selection_failure": BatchSelectionFailure(
                reason="batch_scope_mismatch",
                run_id="new-sync",
                occurred_at=NOW,
                member_ids=(original.batch.members[0].finding_id,),
            )
        }
    )
    existing = original.model_copy(update={"batch": latest_batch})
    attempt = BatchExecutionScopeService().resolve(original, policy(), run_id="execution").attempt
    incoming = original.model_copy(update={"batch_attempt": attempt, "status": "blocked"})
    snapshots = existing.model_dump(), incoming.model_dump()

    merged = merge_remediation_work_item_state(existing, incoming)

    assert merged.batch == latest_batch
    assert merged.batch_attempt == attempt
    assert merged.status == "blocked"
    assert merge_authoritative_work_item_state(existing, incoming).batch == original.batch
    assert (existing.model_dump(), incoming.model_dump()) == snapshots
