"""Characterize live finding-sync storage through both native provider adapters."""

import re
from dataclasses import replace

import pytest

from zeroone_ops.models.finding_sync import FindingSyncInventory
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.control_plane.work_items.finding_sync_inventory import (
    inventory_records,
    require_scoped_work_item,
)
from zeroone_ops.services.control_plane.work_items.finding_sync_projection import (
    FindingSyncProjection,
)

from .test_batch_finding_sync_coordinator import SCOPE, batch_state, seed
from .test_batch_finding_sync_coordinator import harness as harness


def _replace_state(harness, number, state):
    """Replace provider authority without modifying a previously returned native snapshot."""
    client, service, _ = harness
    body_field = "body" if client.provider == "github" else "description"
    client.issues[number] = client.issues[number].model_copy(
        update={body_field: service.upsert_service.renderer.render_body(state)}
    )


def test_live_inventory_query_order_and_native_states(harness):
    client, _, storage = harness
    opened = batch_state(status="approved")
    seed(harness, opened)
    for status in ("policy_deferred", "capacity_deferred", "dismissed", "blocked"):
        seed(harness, batch_state(status=status), is_open=False)
    assert client.queries == []

    inventory = storage.load_inventory(repository_scope=SCOPE)

    assert client.queries == [(True, ("zeroone-work-item",))] + [
        (False, ("zeroone-work-item", f"zeroone-status:{status}"))
        for status in (
            "policy_deferred",
            "capacity_deferred",
            "dismissed",
            "candidate",
            "approved",
            "in_progress",
            "blocked",
            "review_feedback_required",
            "review_revision_queued",
        )
    ]
    assert inventory.open_work_items[0].work_item == opened
    assert [record.issue_number for record in inventory_records(inventory)] == [1, 2, 3, 4, 5]
    assert inventory.closed_nonterminal_batches[0].work_item.status == "blocked"
    assert not inventory.closed_nonterminal_batches[0].is_open
    assert client.calls == []


def test_exact_reread_preserves_earlier_native_snapshot(harness, monkeypatch):
    client, service, storage = harness
    original = batch_state(status="approved")
    seed(harness, original)
    first_issue = client.issues[1]
    first = storage.load_inventory(repository_scope=SCOPE).open_work_items[0]
    updated = original.model_copy(update={"status": "in_progress"})
    _replace_state(harness, 1, updated)
    second_issue = client.issues[1]
    second = storage.read_work_item(repository_scope=SCOPE, issue_number=1)
    native_snapshots = []
    persist = service.update_existing_work_item

    def record_update(**kwargs):
        native_snapshots.append(kwargs["existing"])
        return persist(**kwargs)

    monkeypatch.setattr(service, "update_existing_work_item", record_update)
    storage.update_existing_work_item(
        repository_scope=SCOPE,
        existing=first,
        work_item=original.model_copy(update={"summary": "First projection"}),
    )
    storage.update_existing_work_item(
        repository_scope=SCOPE,
        existing=second,
        work_item=updated.model_copy(update={"summary": "Second projection"}),
    )

    assert native_snapshots[0].issue is first_issue
    assert native_snapshots[1].issue is second_issue
    assert first.work_item == original and second.work_item == updated
    assert [action for action, _ in client.calls] == ["get", "update", "update"]


def test_actual_write_response_drives_later_updates(harness, monkeypatch):
    client, service, storage = harness
    seed(harness, batch_state(status="approved"))
    existing = storage.read_work_item(repository_scope=SCOPE, issue_number=1)
    persist = service.update_existing_work_item
    returned_native = []
    incoming_native = []

    def authoritative_update(**kwargs):
        incoming_native.append(kwargs["existing"])
        result = persist(**kwargs)
        actual = type(result)(
            issue=result.issue.model_copy(update={"web_url": "https://example/actual"}),
            work_item=result.work_item.model_copy(update={"summary": "Actual summary"}),
            action="unchanged",
        )
        returned_native.append(actual)
        return actual

    monkeypatch.setattr(service, "update_existing_work_item", authoritative_update)
    result = storage.update_existing_work_item(
        repository_scope=SCOPE, existing=existing, work_item=existing.work_item
    )
    assert result.action == "unchanged"
    assert result.record.issue_url == "https://example/actual"
    assert result.record.work_item.summary == "Actual summary"
    storage.update_existing_work_item(
        repository_scope=SCOPE, existing=result.record, work_item=result.record.work_item
    )
    assert incoming_native[1].issue is returned_native[0].issue
    assert incoming_native[1].work_item is returned_native[0].work_item
    assert len([action for action, _ in client.calls if action == "get"]) == 1


@pytest.mark.parametrize("initially_open", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_projection_state_changes_only_after_successful_native_transition(
    harness, initially_open, fail
):
    client, _, storage = harness
    seed(
        harness,
        batch_state(status="approved" if initially_open else "policy_deferred"),
        is_open=initially_open,
    )
    original = storage.read_work_item(repository_scope=SCOPE, issue_number=1)
    action = "close" if initially_open else "reopen"
    operation = storage.close_work_item_issue if initially_open else storage.reopen_work_item_issue
    if fail:
        client.fail = action
        with pytest.raises(RuntimeError, match="unavailable"):
            operation(repository_scope=SCOPE, issue_number=1)
    else:
        operation(repository_scope=SCOPE, issue_number=1)
    client.fail = None
    result = storage.update_existing_work_item(
        repository_scope=SCOPE,
        existing=original,
        work_item=original.work_item.model_copy(update={"summary": "Projected summary"}),
    )

    assert result.record.is_open is (initially_open if fail else not initially_open)
    assert original.is_open is initially_open
    assert [operation for operation, _ in client.calls] == ["get", action, "update"]


@pytest.mark.parametrize(
    "operation, status, initially_open, expected",
    [
        ("close", "policy_deferred", True, ["update", "close"]),
        ("activate", "approved", False, ["reopen", "update"]),
        ("block", "blocked", False, ["update", "reopen"]),
    ],
)
def test_projection_write_order_remains_explicit(
    harness, operation, status, initially_open, expected
):
    client, _, storage = harness
    state = batch_state(status="candidate" if initially_open else "policy_deferred")
    seed(harness, state, is_open=initially_open)
    original = storage.read_work_item(repository_scope=SCOPE, issue_number=1)
    client.calls.clear()

    getattr(FindingSyncProjection(storage), operation)(
        SCOPE, original, state.model_copy(update={"status": status})
    )

    assert [action for action, _ in client.calls] == expected


@pytest.mark.parametrize("operation", ["read", "inventory"])
@pytest.mark.parametrize("invalid", ["missing", "missing_scope", "other_scope"])
def test_reads_and_discovery_fail_closed_on_invalid_authority(harness, operation, invalid):
    client, _, storage = harness
    state = batch_state().model_copy(update={"batch": None})
    seed(harness, state)
    if invalid in {"missing_scope", "other_scope"}:
        changed = state.model_copy(
            update={
                "source": state.source.model_copy(
                    update={
                        "repository_scope": None if invalid == "missing_scope" else "other/repo",
                    }
                )
            }
        )
        _replace_state(harness, 1, changed)
    else:
        body_field = "body" if client.provider == "github" else "description"
        client.issues[1] = client.issues[1].model_copy(
            update={
                body_field: "not machine state",
            }
        )
    message = (
        "Cannot establish authoritative work-item state."
        if operation == "read"
        else "Cannot establish complete batch ownership inventory."
    )

    with pytest.raises(ValueError) as error:
        if operation == "read":
            storage.read_work_item(repository_scope=SCOPE, issue_number=1)
        else:
            storage.load_inventory(repository_scope=SCOPE)

    assert str(error.value) == message
    assert client.create_attempts == 0
    assert not any(action in {"update", "close", "reopen"} for action, _ in client.calls)


@pytest.mark.parametrize("operation", ["read", "inventory"])
def test_malformed_json_keeps_provider_parser_error(harness, operation):
    client, _, storage = harness
    seed(harness, batch_state())
    field = "body" if client.provider == "github" else "description"
    body = getattr(client.issues[1], field)
    broken = re.sub(r"```json\n.*?\n```", "```json\n{invalid}\n```", body, flags=re.S)
    assert broken != body
    client.issues[1] = client.issues[1].model_copy(update={field: broken})
    error_type = GitHubClientError if client.provider == "github" else GitLabClientError

    with pytest.raises(error_type, match="invalid JSON"):
        if operation == "read":
            storage.read_work_item(repository_scope=SCOPE, issue_number=1)
        else:
            storage.load_inventory(repository_scope=SCOPE)


@pytest.mark.parametrize("operation", ["read", "inventory"])
def test_parser_exceptions_propagate_without_becoming_empty_inventory(
    harness, monkeypatch, operation
):
    _, service, storage = harness
    seed(harness, batch_state())

    def fail_parse(_body):
        raise RuntimeError("parser failed")

    monkeypatch.setattr(service.lookup_service.parser, "parse_work_item_state", fail_parse)
    with pytest.raises(RuntimeError, match="parser failed"):
        if operation == "read":
            storage.read_work_item(repository_scope=SCOPE, issue_number=1)
        else:
            storage.load_inventory(repository_scope=SCOPE)


def test_listing_failure_is_not_an_empty_inventory(harness):
    client, _, storage = harness
    client.fail = "list"
    with pytest.raises(RuntimeError, match="unavailable"):
        storage.load_inventory(repository_scope=SCOPE)
    assert client.create_attempts == 0


def test_inventory_normalization_retains_conflicts_and_deduplicates_equal_snapshots(harness):
    _, _, storage = harness
    seed(harness, batch_state())
    original = storage.read_work_item(repository_scope=SCOPE, issue_number=1)
    equal = replace(original)
    conflicting = replace(
        original, work_item=original.work_item.model_copy(update={"status": "blocked"})
    )
    inventory = FindingSyncInventory(
        open_work_items=(original, equal),
        policy_deferred_work_items=(),
        capacity_deferred_work_items=(),
        dismissed_work_items=(),
        closed_nonterminal_batches=(conflicting,),
    )

    assert inventory_records(inventory) == (original, conflicting)


def test_scope_guard_retains_original_state_and_does_not_mutate_it():
    state = batch_state()
    before = state.model_dump_json()

    assert (
        require_scoped_work_item(state, repository_scope=SCOPE, error_message="Invalid scope")
        is state
    )
    assert state.model_dump_json() == before


@pytest.mark.parametrize("scope", [None, "other/repo"])
def test_scope_guard_preserves_supplied_failure_message_and_input(scope):
    state = batch_state().model_copy(update={"batch": None})
    state.source = state.source.model_copy(update={"repository_scope": scope})
    before = state.model_dump_json()

    with pytest.raises(ValueError, match="Exact caller message"):
        require_scoped_work_item(
            state, repository_scope=SCOPE, error_message="Exact caller message"
        )

    assert state.model_dump_json() == before
