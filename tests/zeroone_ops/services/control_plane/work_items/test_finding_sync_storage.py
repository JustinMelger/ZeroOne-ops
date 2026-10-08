"""Contract tests for both native finding-sync storage adapters."""

import pytest

from zeroone_ops.services.control_plane.work_items.github_finding_sync_storage import (
    GitHubFindingSyncStorage,
)
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_storage import (
    GitLabFindingSyncStorage,
)

from .test_finding_sync_coordinator import INVENTORY_CALLS, SCOPE, _boundary


def _storage(provider, boundary):
    storage_type = GitHubFindingSyncStorage if provider == "github" else GitLabFindingSyncStorage
    return storage_type(boundary)


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_adapter_retains_exact_native_snapshot_after_authoritative_reread(provider):
    _, boundary, _ = _boundary(provider, status="approved")
    original = boundary.list_open_work_items.return_value[0]
    storage = _storage(provider, boundary)
    boundary.list_open_work_items.assert_not_called()
    inventory = storage.load_inventory(repository_scope=SCOPE)
    assert [call[0] for call in boundary.mock_calls] == INVENTORY_CALLS
    record = inventory.open_work_items[0]
    changed = type(original)(
        issue=original.issue.model_copy(update={"title": "Latest title"}),
        work_item=original.work_item.model_copy(update={"status": "in_progress"}),
    )
    boundary.find_open_work_item_by_source.return_value = changed
    reread = storage.find_open_work_item_by_source(
        repository_scope=SCOPE, kind="remediation", source=original.work_item.source
    )
    storage.update_existing_work_item(
        repository_scope=SCOPE, existing=record, work_item=record.work_item
    )
    assert boundary.update_existing_work_item.call_args.kwargs["existing"] is original
    storage.update_existing_work_item(
        repository_scope=SCOPE, existing=reread, work_item=reread.work_item
    )
    assert boundary.update_existing_work_item.call_args.kwargs["existing"] is changed


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_adapter_write_returns_actual_persisted_state_url_and_action(provider):
    _, boundary, _ = _boundary(provider, status="approved")
    storage = _storage(provider, boundary)
    record = storage.load_inventory(repository_scope=SCOPE).open_work_items[0]
    original_write = boundary.update_existing_work_item.side_effect

    def authoritative_write(**kwargs):
        result = original_write(**kwargs)
        return type(result)(
            issue=result.issue.model_copy(update={"web_url": "https://example/actual"}),
            work_item=result.work_item.model_copy(update={"summary": "Actual summary"}),
            action="unchanged",
        )

    boundary.update_existing_work_item.side_effect = authoritative_write
    result = storage.update_existing_work_item(
        repository_scope=SCOPE, existing=record, work_item=record.work_item
    )
    assert result.action == "unchanged"
    assert result.record.issue_url == "https://example/actual"
    assert result.record.work_item.summary == "Actual summary"
    storage.update_existing_work_item(
        repository_scope=SCOPE, existing=result.record, work_item=result.record.work_item
    )
    assert (
        boundary.update_existing_work_item.call_args.kwargs["existing"].issue.web_url
        == "https://example/actual"
    )


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_adapter_passes_original_dismissal_inventory_to_upsert(provider):
    _, boundary, _ = _boundary(provider, status="dismissed", closed=True)
    original = boundary.list_closed_dismissed_work_items.return_value[0]
    storage = _storage(provider, boundary)
    inventory = storage.load_inventory(repository_scope=SCOPE)
    storage.upsert_work_item(
        repository_scope=SCOPE,
        work_item=original.work_item,
        dismissed_inventory=inventory.dismissed_work_items,
    )
    assert boundary.upsert_work_item.call_args.kwargs["dismissed_inventory"] == [original]
    assert boundary.upsert_work_item.call_args.kwargs["dismissed_inventory"][0] is original


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_adapter_reopen_result_reflects_known_projection_without_extra_reads(provider):
    _, boundary, _ = _boundary(provider, status="policy_deferred", closed=True)
    storage = _storage(provider, boundary)
    record = storage.load_inventory(repository_scope=SCOPE).policy_deferred_work_items[0]
    storage.reopen_work_item_issue(repository_scope=SCOPE, issue_number=record.issue_number)
    result = storage.update_existing_work_item(
        repository_scope=SCOPE,
        existing=record,
        work_item=record.work_item.model_copy(update={"status": "approved"}),
    )
    assert result.record.is_open
    assert not record.is_open
    assert [call[0] for call in boundary.mock_calls] == INVENTORY_CALLS + [
        "reopen_work_item_issue",
        "update_existing_work_item",
    ]
