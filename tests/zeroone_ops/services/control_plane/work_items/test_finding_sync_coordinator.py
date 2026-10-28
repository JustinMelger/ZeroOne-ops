"""Characterize finding-sync orchestration through both provider boundaries."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemClaim
from zeroone_ops.services.control_plane.work_items.github_finding_sync_service import (
    GitHubFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_upsert_service import (
    GitHubWorkItemUpsertResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service import (
    GitLabFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_upsert_service import (
    GitLabWorkItemUpsertResult,
)

from .test_batch_finding_sync_coordinator import (
    SCOPE as NATIVE_SCOPE,
)
from .test_batch_finding_sync_coordinator import (
    batch_state,
    finding,
    policy,
    seed,
    stored,
)
from .test_batch_finding_sync_coordinator import harness as harness
from .test_support import build_work_item

SCOPE = "octo-org/octo-repo"
INVENTORY_CALLS = [
    "list_open_work_items",
    "list_closed_policy_deferred_work_items",
    "list_closed_capacity_deferred_work_items",
    "list_closed_dismissed_work_items",
]


def _boundary(provider, *, status=None, closed=False):
    boundary = Mock(spec=GitHubWorkItemService if provider == "github" else GitLabWorkItemService)
    state = build_work_item(status=status or "approved")
    if provider == "github":
        issue = GitHubIssueInfo(
            id=11, number=11, web_url="https://example/11", title="Work", body=""
        )
        lookup_type = GitHubWorkItemLookupResult
        result_type = GitHubWorkItemUpsertResult
        service = GitHubFindingSyncService(work_item_service=boundary)
        scope = {"repository_id": SCOPE}
    else:
        issue = GitLabIssueInfo(
            id=11, iid=11, web_url="https://example/11", title="Work", description=""
        )
        lookup_type = GitLabWorkItemLookupResult
        result_type = GitLabWorkItemUpsertResult
        service = GitLabFindingSyncService(work_item_service=boundary)
        scope = {"project_id": SCOPE}
    lookup = lookup_type(issue=issue, work_item=state, is_open=not closed)
    for name in INVENTORY_CALLS:
        getattr(boundary, name).return_value = []
    if status is not None:
        name = f"list_closed_{status}_work_items" if closed else "list_open_work_items"
        getattr(boundary, name).return_value = [lookup]
    boundary.find_open_work_item_by_source.return_value = lookup
    boundary.update_existing_work_item.side_effect = lambda **kwargs: result_type(
        issue=issue, work_item=kwargs["work_item"], action="updated"
    )
    boundary.upsert_work_item.side_effect = lambda **kwargs: result_type(
        issue=issue, work_item=kwargs["work_item"], action="created"
    )
    return service, boundary, scope


def public_sync(harness, findings=(), **changes):
    client, boundary, _ = harness
    service_type = (
        GitHubFindingSyncService if client.provider == "github" else GitLabFindingSyncService
    )
    return service_type(work_item_service=boundary).sync(
        **{"repository_id" if client.provider == "github" else "project_id": NATIVE_SCOPE},
        **(
            dict(findings=list(findings), policy_state=policy(), managed_source_ids={"ruff-sarif"})
            | changes
        ),
    )


@pytest.mark.parametrize(("limit", "expected_size"), [(None, 5), (1, 1), (10, 7)])
def test_public_services_respect_default_and_explicit_batch_limits(harness, limit, expected_size):
    findings = [finding(f"f{number:02}") for number in range(7)]
    options = {} if limit is None else {"max_findings_per_work_item": limit}
    result = public_sync(harness, findings, **options)
    assert result.created_count == result.promoted_count == 1
    assert result.selected_member_count == expected_size
    assert result.backlog_only_count == len(findings) - expected_size
    assert len(stored(harness).batch.members) == expected_size


def single_state(status="approved", **changes):
    state = batch_state(status=status).model_copy(
        update={
            "batch": None,
            "work_item_id": "historical-single",
        }
    )
    return state.model_copy(
        update={
            "source": state.source.model_copy(update={"source_item_key": "a"}),
            **changes,
        }
    )


@pytest.mark.parametrize(
    "status", ["candidate", "approved", "policy_deferred", "capacity_deferred"]
)
@pytest.mark.parametrize("persist", [False, True])
@pytest.mark.parametrize("reported", [False, True])
def test_historical_single_policy_and_absence_projection(harness, status, persist, reported):
    original = single_state(status)
    seed(harness, original, is_open=status in {"candidate", "approved"})
    result = public_sync(
        harness, [finding()] if reported else [], policy_state=policy("low"), persist=persist
    )
    actual = stored(harness)
    assert actual.batch is None
    if not persist:
        assert actual == original
        assert all(action == "get" for action, _ in harness[0].calls)
    else:
        assert actual.status == ("policy_deferred" if reported else "completed")
        assert actual.resolution == (None if reported else "no_longer_detected")
        assert not harness[0].open[1]
        assert actual.work_item_id == original.work_item_id
        actions = [action for action, _ in harness[0].calls]
        if status in {"candidate", "approved"}:
            assert actions.index("update") < actions.index("close")
    assert result.created_count == 0


@pytest.mark.parametrize(
    "status",
    [
        "in_progress",
        "blocked",
        "dismissed",
        "review_feedback_required",
        "review_revision_queued",
    ],
)
@pytest.mark.parametrize("reported", [False, True])
def test_historical_protected_work_is_never_rewritten(harness, status, reported):
    original = single_state(
        status, linked_change_request=ChangeRequestRef(number=9, web_url="https://example/9")
    )
    seed(harness, original)
    result = public_sync(harness, [finding()] if reported else [], policy_state=policy("low"))
    assert stored(harness) == original
    assert result.created_count == result.no_longer_detected_count == 0
    assert all(
        action in ({"get", "close"} if status == "dismissed" else {"get"})
        for action, _ in harness[0].calls
    )


@pytest.mark.parametrize(
    "status", ["candidate", "approved", "policy_deferred", "capacity_deferred"]
)
def test_missing_unmanaged_single_inventory_is_not_absence(harness, status):
    original = single_state(status)
    seed(harness, original, is_open=status in {"candidate", "approved"})
    public_sync(harness, managed_source_ids=set())
    assert stored(harness) == original


@pytest.mark.parametrize("change", ["linked", "in_progress", "claim"])
def test_single_transition_reread_retains_concurrent_authority(harness, change):
    original = single_state()
    seed(harness, original)
    changed = original.model_copy(
        update={"linked_change_request": ChangeRequestRef(number=9, web_url="https://example/9")}
        if change == "linked"
        else {"status": "in_progress"}
        if change == "in_progress"
        else {"claim": WorkItemClaim(claimed_at=datetime(2026, 1, 1, tzinfo=UTC), run_id="other")}
    )

    def concurrent_change(number):
        renderer = harness[1].upsert_service.renderer
        body_field = "body" if harness[0].provider == "github" else "description"
        harness[0].issues[number] = (
            harness[0].issues[number].model_copy(update={body_field: renderer.render_body(changed)})
        )

    harness[0].on_get = concurrent_change
    result = public_sync(harness)
    assert stored(harness) == changed
    assert result.projection_warning_count == 1
    assert not any(action in {"update", "close"} for action, _ in harness[0].calls)


@pytest.mark.parametrize("failure", ["get", "update", "close", "reopen"])
def test_projection_failures_warn_without_creating_duplicate_work(harness, failure):
    state = single_state("policy_deferred" if failure == "reopen" else "approved")
    seed(harness, state, is_open=failure != "reopen")
    harness[0].fail = failure
    result = public_sync(harness, [finding()] if failure == "reopen" else [])
    assert result.projection_warning_count == 1
    assert harness[0].create_attempts == 0


def test_required_inventory_failure_propagates(harness):
    harness[0].fail = "list"
    with pytest.raises(RuntimeError, match="unavailable"):
        public_sync(harness, [finding()])
    assert harness[0].create_attempts == 0


def test_existing_singles_remain_separate_from_new_batch(harness):
    original = single_state("candidate")
    seed(harness, original)
    result = public_sync(harness, [finding(), finding("b"), finding("c")])
    assert stored(harness).batch is None
    assert stored(harness).work_item_id == original.work_item_id
    assert result.created_count == 0  # Same-group ownership prevents a parallel batch.
    assert stored(harness).status == "approved"


def test_candidate_capacity_deferral_reopens_after_capacity_frees(harness):
    candidate = single_state("candidate")
    seed(harness, candidate)
    active = single_state("in_progress").model_copy(
        update={
            "work_item_id": "active-single",
            "source": candidate.source.model_copy(update={"source_item_key": "active"}),
        }
    )
    seed(harness, active)
    public_sync(harness, [finding()], max_active_work_items=1)
    assert stored(harness).status == "capacity_deferred"
    assert not harness[0].open[1]
    del harness[0].issues[2]
    del harness[0].open[2]
    result = public_sync(harness, [finding()], max_active_work_items=1)
    assert stored(harness).status == "approved"
    assert harness[0].open[1]
    assert result.policy_reactivated_count == 1
