"""Revalidate absence completion through both providers without extra reads."""

from unittest.mock import Mock

import pytest

from zeroone_ops.models.remediation import RemediationCompletionRequest
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemClaim
from zeroone_ops.services.control_plane.work_items.work_item_completion_service import (
    complete_absent_batch,
)
from zeroone_ops.services.remediation.control_plane import (
    GitHubRemediationControlPlane,
    GitLabRemediationControlPlane,
)
from zeroone_ops.services.remediation.remediation_execution_adapter import (
    control_plane_work_item_to_execution_target,
)

from .test_batch_finding_sync_coordinator import NOW, SCOPE, batch_state, seed, stored
from .test_batch_finding_sync_coordinator import harness as harness


def absent_state():
    state = batch_state(
        status="in_progress", claim=WorkItemClaim(claimed_at=NOW, run_id="selected")
    )
    return state.model_copy(
        update={
            "batch": state.batch.model_copy(
                update={
                    "observations": tuple(
                        observation.model_copy(update={"last_confirmed_presence": "absent"})
                        for observation in state.batch.observations
                    )
                }
            )
        }
    )


@pytest.mark.parametrize(
    "drift",
    [
        "none",
        "detected",
        "unknown",
        "blocked",
        "linked",
        "claim",
        "attempt",
        "closed",
        "update_failure",
    ],
)
def test_provider_completion_uses_latest_authority_and_never_creates(harness, drift):
    client, service, _ = harness
    selected = absent_state()
    current = selected
    if drift in {"detected", "unknown"}:
        observation = selected.batch.observations[0].model_copy(
            update=(
                {"last_confirmed_presence": "detected"}
                if drift == "detected"
                else {"freshness": "unknown"}
            )
        )
        current = selected.model_copy(
            update={"batch": selected.batch.model_copy(update={"observations": (observation,)})}
        )
    elif drift == "blocked":
        current = selected.model_copy(update={"status": "blocked"})
    elif drift == "linked":
        current = selected.model_copy(
            update={
                "linked_change_request": ChangeRequestRef(number=7, web_url="https://example/pr/7")
            }
        )
    elif drift == "claim":
        current = selected.model_copy(
            update={"claim": WorkItemClaim(claimed_at=NOW, run_id="another-run")}
        )
    elif drift == "attempt":
        current = selected.model_copy(update={"attempt_number": 2})
    seed(harness, current, is_open=drift != "closed")
    if drift == "update_failure":
        client.fail = "update"
    control_plane = (
        GitHubRemediationControlPlane(work_item_service=service, repository_id=SCOPE)
        if client.provider == "github"
        else GitLabRemediationControlPlane(work_item_service=service, project_id=SCOPE)
    )

    result = control_plane.complete_absent_batch(
        selected_issue=control_plane_work_item_to_execution_target(selected),
        existing_work_item=selected,
    )

    assert result.completed == (drift == "none")
    assert len(client.queries) == 1
    assert client.create_attempts == 0
    assert not any(action in {"close", "reopen", "create"} for action, _ in client.calls)
    if drift == "none":
        persisted = stored(harness)
        assert persisted.status == "completed"
        assert persisted.resolution == "no_longer_detected"
        assert persisted.claim is None
        assert persisted.batch == selected.batch
    else:
        assert stored(harness) == current
        assert client.calls.count(("update", 1)) == (1 if drift == "update_failure" else 0)


def test_idempotent_completion_does_not_write_again():
    selected = absent_state()
    completed = selected.model_copy(
        update={"status": "completed", "resolution": "no_longer_detected", "claim": None}
    )
    write = Mock()
    result = complete_absent_batch(
        existing=completed,
        request=RemediationCompletionRequest(completed, selected.claim),
        persist_work_item=write,
    )
    assert result.completed
    write.assert_not_called()


def test_completion_does_not_claim_success_from_noncompleted_persistence_response():
    selected = absent_state()
    requested = selected.model_copy(
        update={"status": "completed", "resolution": "no_longer_detected", "claim": None}
    )
    result = complete_absent_batch(
        existing=selected,
        request=RemediationCompletionRequest(requested, selected.claim),
        persist_work_item=Mock(return_value=selected),
    )
    assert not result.completed
