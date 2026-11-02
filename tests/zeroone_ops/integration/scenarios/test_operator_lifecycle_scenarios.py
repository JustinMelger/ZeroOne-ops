"""Exercise authorized operator recovery and lifecycle through real provider services."""

from copy import deepcopy
from datetime import timedelta

import httpx
import pytest

from zeroone_ops.models.work_item import WorkItemClaim

from .harness import RUN_ID, compose_scenario
from .operator_loop import ACTION_AT, COMMAND_AT, compose_operator_loop
from .provider_api import ScenarioProviderAPI
from .repository import TARGET_PATH, create_repository, git
from .revision import configure_request_lookup, persist_work_item


@pytest.fixture(params=["github", "gitlab"])
def operator_loop(request, tmp_path, monkeypatch):
    """Publish one real local batch before exercising provider-native operator events."""
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.control_plane.utc_now",
        lambda: COMMAND_AT + timedelta(seconds=30),
    )
    repository = create_repository(tmp_path)
    api = ScenarioProviderAPI(request.param)
    api.repository_permissions.update(operator="admin", outsider="write")
    api.project_access_levels.update({7: 40, 8: 30})
    with httpx.Client(
        base_url="https://provider.invalid",
        transport=httpx.MockTransport(lambda request: api.respond(request)),
    ) as http:
        harness = compose_scenario(repository, api, http, (None,), monkeypatch)
        harness.sync("promotion")
        summary = harness.runner.run(record=harness.runs.start_run(RUN_ID), active_dry_run=False)
        assert summary.status.value == "change_request_created", summary.message
        api.branch_head_lookup = lambda branch: git(
            repository.remote, "rev-parse", f"refs/heads/{branch}"
        )
        configure_request_lookup(harness, http)
        yield compose_operator_loop(harness, repository, http)


def test_authorized_revision_then_merge_completes_work(operator_loop, monkeypatch):
    loop = operator_loop
    harness, api = loop.harness, loop.harness.api
    original = loop.feedback()
    reference = loop.comment(10)
    command = loop.requeue(10)
    assert command.status.value == "synced" and "1 accepted" in command.message
    queued = harness.work_item()
    assert queued.status == "review_revision_queued"
    assert queued.review_revision_request.request_reference == reference
    assert queued.last_revision_command.actor == "operator"
    assert queued.last_revision_command.occurred_at == COMMAND_AT
    assert queued.review_revision_request.reviewed_sha == original.projected_review.reviewed_sha
    assert loop.reconcile().unchanged_count == 1
    assert harness.work_item() == queued

    revision, model = loop.revise(monkeypatch, succeeds=True)
    revised = harness.work_item()
    assert revision.status.value == "change_request_created", revision.message
    assert model.analysis_count == model.edit_count == 1
    assert revised.status == "in_progress" and revised.claim is None
    assert revised.review_revision_request is None
    assert revised.last_revision_command.request_reference == reference
    assert revised.linked_change_request == original.linked_change_request
    assert revised.batch.members == original.batch.members
    assert revised.batch_attempt.members == original.batch_attempt.members
    assert revised.semantic_safety.assessment.intended_behavior == "Annotate the same value"
    body = str(
        next(iter(api.issues.values()))["body" if api.platform == "github" else "description"]
    )
    assert "Change Rationale" in body
    request = next(iter(api.requests.values()))
    description = str(request["body" if api.platform == "github" else "description"])
    assert "Validation passed" in description and "Change Rationale" in description
    branch = git(loop.repository.root, "branch", "--show-current")
    remote_sha = git(loop.repository.remote, "rev-parse", f"refs/heads/{branch}")
    assert (
        git(loop.repository.remote, "rev-parse", f"{remote_sha}^")
        == queued.projected_review.reviewed_sha
    )
    assert (
        git(loop.repository.remote, "diff", "--name-only", f"{remote_sha}^", remote_sha)
        == TARGET_PATH
    )
    assert len(api.requests) == 1
    assert harness.sync("still-active").promoted_count == 0
    before_merge = harness.work_item()

    loop.request_state("merged")
    api.issue_writes.clear()
    result = loop.reconcile()
    final = harness.work_item()
    assert result.completed_count == result.closed_issue_count == 1
    assert final.status == "completed" and final.claim is None
    assert final.batch == before_merge.batch and final.batch_attempt == revised.batch_attempt
    assert final.semantic_safety == revised.semantic_safety
    assert final.last_revision_command == revised.last_revision_command
    assert final.projected_review == revised.projected_review
    assert final.linked_change_request == revised.linked_change_request
    assert [harness.parse(write).status for write in api.issue_writes] == ["completed", "completed"]
    assert api.issue_writes[0]["state"] != "closed" and api.issue_writes[1]["state"] == "closed"
    writes = len(api.issue_writes)
    repeated = loop.reconcile()
    assert repeated.completed_count == repeated.closed_issue_count == 0
    assert len(api.issue_writes) == writes
    assert len(api.requests) == 1
    assert model.analysis_count == model.edit_count == 1


def test_failed_revision_consumes_command_and_requires_new_authorization(
    operator_loop, monkeypatch
):
    loop = operator_loop
    harness, api = loop.harness, loop.harness.api
    original = loop.feedback()
    reference = loop.comment(10)
    assert "1 accepted" in loop.requeue(10).message
    source = loop.repository.source.read_text()
    workspace_status = git(loop.repository.root, "status", "--porcelain")
    summary, model = loop.revise(monkeypatch, succeeds=False)
    failed = harness.work_item()
    assert summary.status.value == "failed"
    assert model.analysis_count == 1 and model.edit_count == 2
    assert failed.status == "review_feedback_required"
    assert failed.claim is None and failed.review_revision_request is None
    assert failed.last_revision_command.request_reference == reference
    assert failed.linked_change_request == original.linked_change_request
    assert failed.projected_review.feedback == original.projected_review.feedback
    assert failed.batch.members == original.batch.members
    assert failed.batch_attempt.members == original.batch_attempt.members
    assert "NameError" in failed.execution_failure.diagnostic_excerpt
    assert loop.repository.source.read_text() == source
    branch = git(loop.repository.root, "branch", "--show-current")
    sha = original.projected_review.reviewed_sha
    assert git(loop.repository.remote, "rev-parse", f"refs/heads/{branch}") == sha
    assert git(loop.repository.root, "rev-parse", "HEAD") == sha
    assert git(loop.repository.root, "status", "--porcelain") == workspace_status
    writes = len(api.issue_writes)
    replay = loop.requeue(10)
    assert replay.status.value == "no_issue" and "0 accepted" in replay.message
    assert "0 rejected" in replay.message
    assert harness.work_item() == failed and len(api.issue_writes) == writes
    assert model.analysis_count == 1 and model.edit_count == 2
    assert len(api.requests) == 1
    assert git(loop.repository.remote, "rev-parse", f"refs/heads/{branch}") == sha

    later = loop.comment(11, at=COMMAND_AT + timedelta(minutes=1))
    assert "1 accepted" in loop.requeue(11).message
    assert harness.work_item().review_revision_request.request_reference == later
    successful, next_model = loop.revise(monkeypatch, succeeds=True)
    assert successful.status.value == "change_request_created", successful.message
    assert successful.run_id != summary.run_id
    assert next_model.analysis_count == next_model.edit_count == 1
    assert harness.work_item().status == "in_progress"
    assert harness.work_item().last_revision_command.request_reference == later
    assert len(api.requests) == 1
    history = {record.run_id: record for record in harness.runs.state_store.load().runs}
    assert history[summary.run_id].status.value == "failed"
    assert history[successful.run_id].status.value == "change_request_created"


def test_closed_unmerged_request_uses_existing_fresh_recovery(operator_loop):
    loop = operator_loop
    harness, api = loop.harness, loop.harness.api
    original = harness.work_item()
    loop.request_state("closed")
    assert loop.reconcile().blocked_count == 1
    blocked = harness.work_item()
    assert blocked.status == "blocked" and blocked.claim is None
    assert blocked.linked_change_request == original.linked_change_request
    assert next(iter(api.issues.values()))["state"] != "closed"
    reference = loop.comment(10)
    assert "1 accepted" in loop.requeue(10).message
    recovered = harness.work_item()
    assert recovered.status == "approved" and recovered.claim is None
    assert recovered.attempt_number == original.attempt_number + 1
    assert recovered.linked_change_request is None and recovered.batch_attempt is None
    assert recovered.batch == original.batch
    event = recovered.recovery_events[-1]
    assert event.request_reference == reference and event.plan == "start_fresh"
    assert event.prior_change_request == original.linked_change_request
    assert event.occurred_at == COMMAND_AT
    writes = len(api.issue_writes)
    assert "0 accepted" in loop.requeue(10).message
    assert harness.work_item() == recovered and len(api.issue_writes) == writes
    assert len(api.requests) == 1
    assert len(harness.model.analysis_contexts) == len(harness.model.edit_contexts) == 1


@pytest.mark.parametrize(
    "case", ["insufficient_permission", "permission_failure", "stale", "dry_run"]
)
def test_requeue_guards_leave_provider_authority_unchanged(operator_loop, case):
    loop = operator_loop
    harness, api = loop.harness, loop.harness.api
    original = loop.feedback()
    actor = "outsider" if case == "insufficient_permission" else "operator"
    if case == "permission_failure":
        api.repository_permissions["operator"] = None
        api.project_access_levels[7] = None
    loop.comment(10, actor=actor, at=ACTION_AT if case == "stale" else COMMAND_AT)
    issues, requests = deepcopy(api.issues), deepcopy(api.requests)
    writes = len(api.issue_writes)
    result = loop.requeue(10, dry_run=case == "dry_run")
    assert f"{int(case == 'dry_run')} accepted" in result.message
    assert result.status.value == ("synced" if case == "dry_run" else "no_issue")
    if case == "stale":
        assert "1 rejected" in result.message
    elif case != "dry_run":
        assert "0 authorized" in result.message
    assert api.issues == issues and api.requests == requests
    assert harness.work_item() == original and len(api.issue_writes) == writes
    assert len(harness.model.analysis_contexts) == len(harness.model.edit_contexts) == 1


def test_provider_command_discovery_keeps_its_existing_boundary(operator_loop):
    loop = operator_loop
    loop.feedback()
    older = loop.comment(9, at=ACTION_AT + timedelta(seconds=1))
    current = loop.comment(10)
    result = loop.requeue(10)
    assert "1 accepted" in result.message
    selected = current if loop.harness.api.platform == "github" else older
    assert loop.harness.work_item().last_revision_command.request_reference == selected
    assert f"{int(loop.harness.api.platform == 'gitlab')} rejected" in result.message


def test_lifecycle_preserves_open_feedback_and_recovers_stale_revision_claim(operator_loop):
    loop = operator_loop
    feedback = loop.feedback()
    assert loop.reconcile().unchanged_count == 1
    assert loop.harness.work_item() == feedback
    reference = loop.comment(10)
    loop.requeue(10)
    queued = loop.harness.work_item()
    claimed = queued.model_copy(
        update={
            "claim": WorkItemClaim(run_id="interrupted", claimed_at=COMMAND_AT - timedelta(days=2))
        }
    )
    persist_work_item(loop.harness, claimed)
    result = loop.reconcile()
    restored = loop.harness.work_item()
    assert result.recovered_stale_claim_count == 1
    assert restored.status == "review_feedback_required"
    assert restored.claim is None and restored.review_revision_request is None
    assert restored.last_revision_command.request_reference == reference
    assert restored.projected_review == queued.projected_review
    assert restored.batch_attempt == queued.batch_attempt
    assert restored.linked_change_request == queued.linked_change_request


def test_lifecycle_dry_run_previews_completion_without_provider_writes(operator_loop):
    loop = operator_loop
    original = deepcopy(loop.harness.api.issues)
    writes = len(loop.harness.api.issue_writes)
    loop.request_state("merged")
    result = loop.reconcile(persist=False)
    assert result.completed_count == 1 and result.closed_issue_count == 0
    assert loop.harness.api.issues == original
    assert len(loop.harness.api.issue_writes) == writes


@pytest.mark.parametrize("failure", ["request_lookup", "issue_close"])
def test_lifecycle_transport_failures_preserve_authority_and_allow_later_repair(
    operator_loop, monkeypatch, caplog, failure
):
    loop = operator_loop
    harness, api = loop.harness, loop.harness.api
    original = harness.work_item()
    if failure == "issue_close":
        loop.request_state("merged")
    respond = api.respond
    fail = True
    failure_states = []

    def inject(request):
        request_lookup = request.method == "GET" and request.url.path.endswith(
            ("/pulls/100", "/merge_requests/100")
        )
        close = request.method in {"PATCH", "PUT"} and api._payload(request) in (
            {"state": "closed"},
            {"state_event": "close"},
        )
        if fail and (
            (failure == "request_lookup" and request_lookup) or (failure == "issue_close" and close)
        ):
            failure_states.append(harness.work_item().status)
            return httpx.Response(503, json={"message": "Offline injected outage"})
        return respond(request)

    monkeypatch.setattr(api, "respond", inject)
    api.issue_writes.clear()
    result = loop.reconcile()
    current = harness.work_item()
    assert current.status == ("blocked" if failure == "request_lookup" else "completed")
    assert current.linked_change_request == original.linked_change_request
    assert current.batch == original.batch and current.batch_attempt == original.batch_attempt
    assert current.semantic_safety == original.semantic_safety
    assert result.closed_issue_count == 0
    assert next(iter(api.issues.values()))["state"] != "closed"
    warning = (
        "could not load linked change request"
        if failure == "request_lookup"
        else "could not close terminal native issue"
    )
    assert warning in caplog.text
    assert failure_states == ["in_progress" if failure == "request_lookup" else "completed"]
    assert [harness.parse(write).status for write in api.issue_writes] == [current.status]
    fail = False
    repaired = loop.reconcile()
    if failure == "request_lookup":
        assert harness.work_item().status == "in_progress"
        assert repaired.blocked_count == 0
    else:
        assert repaired.completed_count == 0 and repaired.closed_issue_count == 1
        assert harness.work_item() == current
        assert next(iter(api.issues.values()))["state"] == "closed"
