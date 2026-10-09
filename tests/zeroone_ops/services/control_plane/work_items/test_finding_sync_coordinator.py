"""Characterize finding-sync orchestration through both provider boundaries."""

from dataclasses import asdict
from unittest.mock import Mock

import pytest

from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.policy import PolicySeverityStateEntry, PolicyState
from zeroone_ops.models.work_item import ChangeRequestRef
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


def _finding():
    return NormalizedFinding(
        finding_id="AX123",
        source_id="sonarqube",
        title="Fix error",
        summary="Fix error in api.py",
        severity="high",
        repository_path="src/api.py",
        line_start=42,
        remediation_context=RemediationContext(category="static_analysis_fix"),
    )


def _sync(service, scope, *, enabled=True, findings=None, persist=True, managed=True, cap=10):
    return service.sync(
        **scope,
        findings=[_finding()] if findings is None else findings,
        policy_state=PolicyState(
            severity_policy=[PolicySeverityStateEntry(severity="high", enabled=enabled)]
        ),
        managed_source_ids={"sonarqube"} if managed else None,
        max_active_work_items=cap,
        persist=persist,
        run_id="sync-123",
    )


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("persist", [False, True])
@pytest.mark.parametrize(
    "scenario", ["new", "defer", "reopen", "missing", "missing_closed", "full"]
)
def test_provider_characterization_transition_order_and_counts(provider, persist, scenario):
    status = {
        "new": None,
        "defer": "approved",
        "reopen": "policy_deferred",
        "missing": "candidate",
        "missing_closed": "capacity_deferred",
        "full": "candidate",
    }[scenario]
    service, boundary, scope = _boundary(
        provider, status=status, closed=scenario in {"reopen", "missing_closed"}
    )
    if scenario == "full":
        active = boundary.list_open_work_items.return_value[0]
        boundary.list_open_work_items.return_value.append(
            type(active)(
                issue=active.issue.model_copy(
                    update={"number" if provider == "github" else "iid": 12}
                ),
                work_item=build_work_item(status="in_progress").model_copy(
                    update={
                        "source": active.work_item.source.model_copy(
                            update={"source_item_key": "active"}
                        )
                    }
                ),
            )
        )
    result = _sync(
        service,
        scope,
        enabled=scenario != "defer",
        findings=[] if scenario.startswith("missing") else None,
        persist=persist,
        managed=scenario != "full",
        cap=1 if scenario == "full" else 10,
    )
    calls = [call[0] for call in boundary.mock_calls]
    expected = {
        "new": ["upsert_work_item"],
        "defer": [
            "find_open_work_item_by_source",
            "update_existing_work_item",
            "close_work_item_issue",
        ],
        "reopen": ["reopen_work_item_issue", "update_existing_work_item"],
        "missing": [
            "find_open_work_item_by_source",
            "update_existing_work_item",
            "close_work_item_issue",
        ],
        "missing_closed": ["update_existing_work_item"],
        "full": [
            "find_open_work_item_by_source",
            "update_existing_work_item",
            "close_work_item_issue",
        ],
    }[scenario]
    assert calls == INVENTORY_CALLS + (expected if persist else [])
    assert result.promoted_count == int(scenario in {"new", "reopen"})
    assert result.backlog_only_count == int(scenario in {"defer", "full"})
    assert result.created_count == int(persist and scenario == "new")
    assert result.updated_count == int(persist and scenario != "new")
    assert result.policy_deferred_count == int(persist and scenario == "defer")
    assert result.capacity_deferred_count == int(persist and scenario == "full")
    assert result.policy_reactivated_count == int(persist and scenario == "reopen")
    assert result.no_longer_detected_count == int(persist and scenario.startswith("missing"))
    assert result.projection_warning_count == 0
    assert result.normalized_severity_counts == (
        {} if scenario.startswith("missing") else {"high": 1}
    )


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("operation", ["lookup", "update", "close", "reopen", "upsert", "list"])
def test_provider_characterization_failure_boundaries(provider, operation, caplog):
    status = "policy_deferred" if operation == "reopen" else "approved"
    if operation in {"upsert", "list"}:
        status = None
    service, boundary, scope = _boundary(provider, status=status, closed=operation == "reopen")
    name = {
        "lookup": "find_open_work_item_by_source",
        "update": "update_existing_work_item",
        "close": "close_work_item_issue",
        "reopen": "reopen_work_item_issue",
        "upsert": "upsert_work_item",
        "list": "list_open_work_items",
    }[operation]
    getattr(boundary, name).side_effect = RuntimeError("provider failed")
    if operation in {"lookup", "upsert", "list"}:
        with pytest.raises(RuntimeError, match="provider failed"):
            _sync(service, scope, enabled=operation in {"upsert", "list"})
    else:
        result = _sync(service, scope, enabled=operation == "reopen")
        assert result.projection_warning_count == 1
        assert result.updated_count == 0
        label = "GitHub" if provider == "github" else "GitLab"
        suffix = "reactivation projection failed" if operation == "reopen" else "projection failed"
        assert f"{label} policy-deferred {suffix}" in caplog.text
    if operation == "update":
        boundary.close_work_item_issue.assert_not_called()
    if operation == "reopen":
        boundary.update_existing_work_item.assert_not_called()


def test_provider_characterization_full_result_parity():
    results = []
    for provider in ["github", "gitlab"]:
        service, _, scope = _boundary(provider, status="approved")
        results.append(asdict(_sync(service, scope, enabled=False)))
    assert results[0] == results[1]


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_deferred_inventory_growth_does_not_rescan_current_findings(provider):
    class CountingFindings(list):
        def __init__(self, findings):
            super().__init__(findings)
            self.iteration_count = 0

        def __iter__(self):
            self.iteration_count += 1
            return super().__iter__()

    iteration_counts = []
    for deferred_count in [1, 25]:
        service, boundary, scope = _boundary(provider, status="policy_deferred", closed=True)
        original = boundary.list_closed_policy_deferred_work_items.return_value[0]
        deferred = [original]
        for index in range(1, deferred_count):
            deferred.append(
                type(original)(
                    issue=original.issue.model_copy(
                        update={
                            "number" if provider == "github" else "iid": 11 + index,
                        }
                    ),
                    work_item=original.work_item.model_copy(
                        update={
                            "source": original.work_item.source.model_copy(
                                update={
                                    "source_item_key": f"missing-{index}",
                                }
                            ),
                        }
                    ),
                    is_open=False,
                )
            )
        boundary.list_closed_policy_deferred_work_items.return_value = deferred
        findings = CountingFindings([_finding()])

        result = _sync(service, scope, findings=findings, enabled=False)

        assert result.no_longer_detected_count == deferred_count - 1
        assert result.backlog_reason_counts == {"severity_disabled": 1}
        assert boundary.update_existing_work_item.call_count == deferred_count - 1
        boundary.close_work_item_issue.assert_not_called()
        iteration_counts.append(findings.iteration_count)
    assert iteration_counts[0] == iteration_counts[1]


@pytest.mark.parametrize("provider", ["github", "gitlab"])
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
def test_provider_protected_work_retains_execution_evidence(provider, status, reported):
    service, boundary, scope = _boundary(provider, status=status)
    lookup = boundary.list_open_work_items.return_value[0]
    original = lookup.work_item.model_dump()

    result = _sync(service, scope, enabled=False, findings=None if reported else [])

    boundary.update_existing_work_item.assert_not_called()
    boundary.upsert_work_item.assert_not_called()
    boundary.close_work_item_issue.assert_not_called()
    assert lookup.work_item.model_dump() == original
    if status == "dismissed" and reported:
        assert result.backlog_reason_counts == {"dismissed": 1}
    elif reported:
        assert result.retained_protected_count == 1
    else:
        assert result.stale_retained_protected_count == 1


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize(
    "status", ["candidate", "approved", "policy_deferred", "capacity_deferred"]
)
def test_provider_missing_unmanaged_inventory_does_not_change_existing_work(provider, status):
    service, boundary, scope = _boundary(
        provider, status=status, closed=status.endswith("deferred")
    )
    result = _sync(service, scope, findings=[], managed=False)
    assert [call[0] for call in boundary.mock_calls] == INVENTORY_CALLS
    assert result.no_longer_detected_count == 0


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("changed", ["linked", "in_progress", "missing"])
def test_provider_reread_protects_changed_authoritative_work(provider, changed):
    service, boundary, scope = _boundary(provider, status="approved")
    initial = boundary.list_open_work_items.return_value[0]
    if changed == "missing":
        boundary.find_open_work_item_by_source.return_value = None
    else:
        state = initial.work_item.model_copy(
            update=(
                {"status": "in_progress"}
                if changed == "in_progress"
                else {
                    "linked_change_request": ChangeRequestRef(
                        number=7, web_url="https://example/pr/7"
                    )
                }
            )
        )
        boundary.find_open_work_item_by_source.return_value = type(initial)(
            issue=initial.issue, work_item=state
        )
    result = _sync(service, scope, enabled=False)
    assert result.retained_protected_count == 1
    boundary.update_existing_work_item.assert_not_called()
    boundary.close_work_item_issue.assert_not_called()


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_provider_late_dismissal_is_backlog_not_publication(provider):
    service, boundary, scope = _boundary(provider)
    original_write = boundary.upsert_work_item.side_effect

    def suppress(**kwargs):
        result = original_write(**kwargs)
        return type(result)(
            issue=result.issue,
            action="suppressed",
            work_item=result.work_item.model_copy(update={"status": "dismissed"}),
        )

    boundary.upsert_work_item.side_effect = suppress
    result = _sync(service, scope)
    assert result.promoted_count == 0
    assert result.backlog_only_count == 1
    assert result.backlog_reason_counts == {"dismissed": 1}
    assert result.created_count == result.updated_count == result.unchanged_count == 0


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_provider_ambiguous_snapshot_does_not_write(provider):
    service, boundary, scope = _boundary(provider, status="candidate")
    initial = boundary.list_open_work_items.return_value[0]
    boundary.list_open_work_items.return_value.append(initial)
    result = _sync(service, scope)
    assert result.backlog_reason_counts == {"work_item_identity_ambiguous": 1}
    assert result.promoted_count == 0
    assert [call[0] for call in boundary.mock_calls] == INVENTORY_CALLS


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("closed", [False, True])
def test_provider_stale_completion_failure_warns_without_widening_boundary(
    provider, closed, caplog
):
    service, boundary, scope = _boundary(
        provider, status="capacity_deferred" if closed else "candidate", closed=closed
    )
    boundary.update_existing_work_item.side_effect = RuntimeError("provider failed")
    result = _sync(service, scope, findings=[])
    assert result.projection_warning_count == 1
    assert result.no_longer_detected_count == result.updated_count == 0
    boundary.close_work_item_issue.assert_not_called()
    assert "completion projection failed" in caplog.text


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_provider_failed_capacity_closure_preserves_existing_warning_count(provider, caplog):
    service, boundary, scope = _boundary(provider, status="candidate")
    active = boundary.list_open_work_items.return_value[0]
    boundary.list_open_work_items.return_value.append(
        type(active)(
            issue=active.issue.model_copy(update={"number" if provider == "github" else "iid": 12}),
            work_item=build_work_item(status="in_progress").model_copy(
                update={
                    "source": active.work_item.source.model_copy(
                        update={"source_item_key": "active"}
                    )
                }
            ),
        )
    )
    boundary.close_work_item_issue.side_effect = RuntimeError("provider failed")
    result = _sync(service, scope, managed=False, cap=1)
    # Existing capacity projection logs the failure without incrementing this counter.
    assert result.projection_warning_count == 0
    assert result.capacity_deferred_count == result.updated_count == 0
    assert "capacity-deferred projection failed" in caplog.text
    assert (
        boundary.update_existing_work_item.call_args.kwargs["work_item"].status
        == "capacity_deferred"
    )
