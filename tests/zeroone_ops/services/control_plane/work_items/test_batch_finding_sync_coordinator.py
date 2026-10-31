"""Exercise identical finding-sync contracts through both real storage adapters."""

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.finding_batch import BatchMemberObservation, WorkItemBatch
from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.policy import PolicySeverityStateEntry, PolicyState
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    WorkItemClaim,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.control_plane.work_items.finding_sync_coordinator import (
    FindingSyncCoordinator,
)
from zeroone_ops.services.control_plane.work_items.github_finding_sync_service import (
    GitHubFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.github_finding_sync_storage import (
    GitHubFindingSyncStorage,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service import (
    GitLabFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_storage import (
    GitLabFindingSyncStorage,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.remediation_work_item_selection_service import (
    is_remediation_execution_eligible,
)
from zeroone_ops.services.intake.finding_batch_identity import create_finding_batch_identity
from zeroone_ops.services.intake.finding_batch_ownership import finding_batch_group

SCOPE = "team/repo"
NOW = datetime(2026, 10, 18, tzinfo=UTC)


def finding(
    identifier="a",
    *,
    path="src/routes.py",
    source="ruff-sarif",
    severity="medium",
    rule="F401",
    constraints=None,
):
    return NormalizedFinding(
        finding_id=identifier,
        source_id=source,
        severity=severity,
        title="Unused import",
        summary="Unused import os",
        repository_path=path,
        line_start=10,
        remediation_context=RemediationContext(
            category="static_analysis_fix", diagnostic_code=rule, constraints=constraints
        ),
    )


def policy(*severities):
    return PolicyState(
        severity_policy=[
            PolicySeverityStateEntry(severity=severity, enabled=True)
            for severity in severities or ("high", "medium", "low")
        ]
    )


def batch_state(*, members=None, status="candidate", **changes):
    members = members or [finding()]
    first = members[0]
    identity = create_finding_batch_identity()
    batch = WorkItemBatch.model_validate(
        dict(
            group=finding_batch_group(repository_scope=SCOPE, finding=first),
            members=members,
            observations=[
                BatchMemberObservation.model_validate(
                    dict(
                        finding_id=member.finding_id,
                        last_confirmed_presence="detected",
                        freshness="current",
                        sync_run_id="old",
                        observed_at=NOW,
                        last_confirmed_sync_run_id="old",
                        last_confirmed_finding=member,
                    )
                )
                for member in members
            ],
        )
    )
    return WorkItemState(
        work_item_id=identity.work_item_id,
        kind="remediation",
        status=status,
        source=WorkItemSourceRef(
            source=first.source_id, source_item_key=identity.source_item_key, repository_scope=SCOPE
        ),
        file_path=first.repository_path,
        line=first.line_start,
        summary="Batch",
        severity=first.severity,
        remediation_context=first.remediation_context,
        batch=batch,
        **changes,
    )


class MemoryIssueClient:
    def __init__(self, provider):
        self.provider = provider
        self.issues = {}
        self.open = {}
        self.labels = {}
        self.calls = []
        self.queries = []
        self.fail = None
        self.on_get = None
        self.on_list = None
        self.create_attempts = 0

    def _list(self, is_open, labels):
        self.queries.append((is_open, tuple(labels)))
        if self.on_list:
            self.on_list(self)
        if self.fail == "list":
            raise RuntimeError("unavailable")
        return [
            issue
            for number, issue in sorted(self.issues.items())
            if self.open[number] == is_open and set(labels).issubset(self.labels[number])
        ]

    def list_open_issues(self, *, labels=None, **kwargs):
        return self._list(True, labels or [])

    def list_closed_issues(self, *, labels=None, **kwargs):
        return self._list(False, labels or [])

    def get_issue(self, **kwargs):
        number = kwargs.get("issue_number", kwargs.get("issue_iid"))
        if self.on_get:
            hook, self.on_get = self.on_get, None
            hook(number)
        if self.fail == "get":
            raise RuntimeError("unavailable")
        self.calls.append(("get", number))
        return self.issues[number], self.open[number]

    def create_issue(self, **kwargs):
        self.create_attempts += 1
        if self.fail == "create_before":
            raise RuntimeError("uncertain")
        number = max(self.issues, default=0) + 1
        self.calls.append(("create", number))
        self._store(number, kwargs, True)
        if self.fail == "create_duplicate":
            self._store(number + 1, kwargs, True)
            raise RuntimeError("uncertain duplicate")
        if self.fail == "create_after":
            raise RuntimeError("uncertain")
        return self.issues[number]

    def update_issue(self, **kwargs):
        number = kwargs.get("issue_number", kwargs.get("issue_iid"))
        self.calls.append(("update", number))
        if self.fail == "update":
            raise RuntimeError("unavailable")
        self._store(number, kwargs, self.open[number])
        return self.issues[number]

    def close_issue(self, **kwargs):
        return self._change_open(False, kwargs)

    def reopen_issue(self, **kwargs):
        return self._change_open(True, kwargs)

    def _change_open(self, is_open, kwargs):
        number = kwargs.get("issue_number", kwargs.get("issue_iid"))
        action = "reopen" if is_open else "close"
        self.calls.append((action, number))
        if self.fail == action:
            raise RuntimeError("unavailable")
        self.open[number] = is_open
        return self.issues[number]

    def _store(self, number, fields, is_open):
        common = dict(id=number, title=fields["title"], web_url=f"https://example/issues/{number}")
        self.labels[number] = list(fields["labels"])
        self.open[number] = is_open
        if self.provider == "github":
            issue = GitHubIssueInfo(**common, number=number, body=fields["body"])
        else:
            issue = GitLabIssueInfo(
                **common,
                iid=number,
                description=fields["description"],
                labels=fields["labels"],
                state="opened" if is_open else "closed",
            )
        self.issues[number] = issue


@pytest.fixture(params=["github", "gitlab"])
def harness(request):
    client = MemoryIssueClient(request.param)
    if request.param == "github":
        service = GitHubWorkItemService(client)
        storage = GitHubFindingSyncStorage(service)
    else:
        service = GitLabWorkItemService(client)
        storage = GitLabFindingSyncStorage(service)
    return client, service, storage


def seed(harness, state, *, is_open=True):
    client, service, _ = harness
    number = max(client.issues, default=0) + 1
    renderer = service.upsert_service.renderer
    body_field = "body" if client.provider == "github" else "description"
    client._store(
        number,
        dict(
            title=renderer.render_title(state),
            labels=renderer.render_labels(state),
            **{body_field: renderer.render_body(state)},
        ),
        is_open,
    )
    return number


def stored(harness, number=1):
    return harness[2].read_work_item(repository_scope=SCOPE, issue_number=number).work_item


def sync(harness, findings=(), **changes):
    return FindingSyncCoordinator(harness[2], clock=lambda: NOW).sync(
        **(
            dict(
                repository_scope=SCOPE,
                findings=list(findings),
                policy_state=policy(),
                managed_source_ids={"ruff-sarif"},
                run_id="current",
            )
            | changes
        )
    )


@pytest.mark.parametrize("limit", [None, 10])
def test_create_batch_with_default_or_override_then_reuse_without_expansion(harness, limit):
    findings = [finding(f"f{number:02}") for number in range(23)]
    options = {} if limit is None else {"max_findings_per_work_item": limit}
    expected_size = 5 if limit is None else limit
    result = sync(harness, findings, max_active_work_items=1, **options)
    assert (result.created_count, result.promoted_count, result.selected_member_count) == (
        1,
        1,
        expected_size,
    )
    assert result.backlog_reason_counts == {"batch_overflow": 23 - expected_size}
    state = stored(harness)
    assert len(state.batch.members) == expected_size
    assert f"zeroone-batch:{state.work_item_id.removeprefix('work-')}" in harness[0].labels[1]

    again = sync(harness, findings, max_active_work_items=1)
    assert again.created_count == 0
    assert again.promoted_count == 0
    assert again.backlog_only_count == 23 - expected_size
    assert "owned" not in again.backlog_reason_counts
    assert stored(harness).batch.members == state.batch.members
    assert harness[0].create_attempts == 1


@pytest.mark.parametrize(
    "status", ["candidate", "approved", "policy_deferred", "capacity_deferred"]
)
def test_complete_inventory_absence_precedes_disabled_policy(harness, status):
    seed(harness, batch_state(status=status), is_open=status in {"candidate", "approved"})
    result = sync(harness, policy_state=policy("low"))
    state = stored(harness)
    assert state.status == "completed"
    assert state.resolution == "no_longer_detected"
    assert not harness[0].open[1]
    assert result.no_longer_detected_count == 1


def test_partial_absence_preserves_frozen_membership_and_selects_remaining(harness):
    seed(harness, batch_state(members=[finding("a"), finding("b")]))
    result = sync(harness, [finding("a")])
    state = stored(harness)
    assert state.status == "approved"
    assert len(state.batch.members) == 2
    assert [o.last_confirmed_presence for o in state.batch.observations] == ["detected", "absent"]
    assert result.selected_member_count == 1


def test_unavailable_inventory_retains_confirmed_absence_until_detection(harness):
    seed(harness, batch_state(members=[finding("a"), finding("b")]))
    sync(harness, [finding("a")])
    result = sync(harness, managed_source_ids=set())
    state = stored(harness)
    assert state.status == "approved"
    assert [o.last_confirmed_presence for o in state.batch.observations] == ["detected", "absent"]
    assert all(o.freshness == "unknown" for o in state.batch.observations)
    assert result.unknown_freshness_member_count == 2
    assert result.no_longer_detected_count == 0
    sync(harness, [finding("a"), finding("b")])
    assert all(o.last_confirmed_presence == "detected" for o in stored(harness).batch.observations)


@pytest.mark.parametrize("status", ["policy_deferred", "capacity_deferred"])
def test_deferred_reactivation_reopens_before_active_update(harness, status):
    seed(harness, batch_state(status=status), is_open=False)
    result = sync(harness, [finding()])
    assert stored(harness).status == "approved"
    actions = [action for action, _ in harness[0].calls]
    assert actions.index("reopen") < actions.index("update")
    assert result.policy_reactivated_count == 1


@pytest.mark.parametrize("reverse_order", [False, True])
@pytest.mark.parametrize("failure", [None, "update", "close"])
def test_reactivation_waits_for_confirmed_capacity_release(
    harness, monkeypatch, reverse_order, failure
):
    client = harness[0]
    pending = batch_state(status="capacity_deferred")
    stale = batch_state(members=[finding("old", path="src/old.py")], status="approved")
    states = [(pending, False), (stale, True)]
    if reverse_order:
        states.reverse()
    numbers = {state.work_item_id: seed(harness, state, is_open=opened) for state, opened in states}
    stale_number, pending_number = numbers[stale.work_item_id], numbers[pending.work_item_id]
    if failure:
        method_name = f"{failure}_issue"
        original_method = getattr(client, method_name)

        def fail_release(**kwargs):
            number = kwargs.get("issue_number", kwargs.get("issue_iid"))
            if number == stale_number:
                client.calls.append((failure, number))
                raise RuntimeError("release failed")
            return original_method(**kwargs)

        monkeypatch.setattr(client, method_name, fail_release)

    result = sync(harness, [finding()], max_active_work_items=1)

    assert result.projection_warning_count == int(failure is not None)
    assert result.promoted_count == int(failure is None)
    assert result.policy_reactivated_count == int(failure is None)
    assert client.calls.count(("update", stale_number)) == 1
    if failure:
        assert stored(harness, pending_number).status == "capacity_deferred"
        assert not client.open[pending_number]
        assert ("reopen", pending_number) not in client.calls
        assert result.backlog_reason_counts == {"promotion_capacity_exhausted": 1}
        assert result.no_longer_detected_count == 0
    else:
        assert stored(harness, stale_number).resolution == "no_longer_detected"
        assert not client.open[stale_number]
        assert stored(harness, pending_number).status == "approved"
        assert client.calls.index(("close", stale_number)) < client.calls.index(
            ("reopen", pending_number)
        )
        assert result.no_longer_detected_count == 1


@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize(
    "status", ["approved", "in_progress", "review_feedback_required", "review_revision_queued"]
)
@pytest.mark.parametrize("policy_disabled", [False, True])
def test_active_owned_findings_are_not_backlog_on_repeated_sync(
    harness, single, status, policy_disabled
):
    members = [finding("a"), finding("b")]
    original = batch_state(
        members=members,
        status=status,
        linked_change_request=ChangeRequestRef(number=7, web_url="https://example/mr/7"),
    )
    if single:
        members = members[:1]
        original = original.model_copy(
            update={
                "batch": None,
                "source": original.source.model_copy(update={"source_item_key": "a"}),
            }
        )
    seed(harness, original)
    enabled = policy("low") if policy_disabled else policy()
    for _ in range(2):
        result = sync(harness, members, policy_state=enabled)
        assert result.promoted_count == 0
        assert result.selected_member_count == 0
        assert result.backlog_only_count == 0
        assert result.backlog_reason_counts == {}
        assert result.normalized_severity_counts == {"medium": len(members)}
        assert stored(harness).status == status
    if single:
        assert original.batch is None
    else:
        assert len(original.batch.members) == 2


def test_active_members_and_capacity_backlog_use_distinct_counts(harness):
    active = [finding("a"), finding("b")]
    seed(harness, batch_state(members=active, status="approved"))
    waiting = finding("waiting", path="src/waiting.py")
    result = sync(harness, [*active, waiting], max_active_work_items=1)
    assert result.promoted_count == 0
    assert result.backlog_only_count == 1
    assert result.backlog_reason_counts == {"promotion_capacity_exhausted": 1}
    assert result.normalized_severity_counts == {"medium": 3}


def test_failed_release_does_not_prevent_using_independent_available_capacity(harness, monkeypatch):
    client = harness[0]
    seed(harness, batch_state(status="approved", members=[finding("old", path="src/old.py")]))
    seed(harness, batch_state(status="capacity_deferred"), is_open=False)
    seed(
        harness,
        batch_state(status="capacity_deferred", members=[finding("b", path="src/other.py")]),
        is_open=False,
    )
    original_update = client.update_issue

    def fail_release(**kwargs):
        if kwargs.get("issue_number", kwargs.get("issue_iid")) == 1:
            raise RuntimeError("release failed")
        return original_update(**kwargs)

    monkeypatch.setattr(client, "update_issue", fail_release)
    result = sync(harness, [finding(), finding("b", path="src/other.py")], max_active_work_items=2)
    assert stored(harness, 1).status == "approved"
    assert sorted(stored(harness, number).status for number in (2, 3)) == [
        "approved",
        "capacity_deferred",
    ]
    assert result.promoted_count == 1
    assert result.projection_warning_count == 1
    assert result.backlog_only_count == 1


def test_dry_run_simulates_release_before_reopening_without_writes(harness):
    seed(harness, batch_state(status="capacity_deferred"), is_open=False)
    seed(harness, batch_state(status="approved", members=[finding("old", path="src/old.py")]))
    before = dict(harness[0].issues)
    result = sync(harness, [finding()], max_active_work_items=1, persist=False)
    assert result.no_longer_detected_count == 1
    assert result.promoted_count == 1
    assert result.policy_reactivated_count == 1
    assert result.backlog_only_count == 0
    assert harness[0].issues == before
    assert not harness[0].open[1]
    assert not any(
        action in {"update", "create", "close", "reopen"} for action, _ in harness[0].calls
    )


def test_policy_then_capacity_deferral_close_after_state_update(harness):
    seed(harness, batch_state(status="approved"))
    result = sync(harness, [finding()], policy_state=policy("low"))
    assert stored(harness).status == "policy_deferred"
    actions = [action for action, _ in harness[0].calls]
    assert actions.index("update") < actions.index("close")
    assert result.policy_deferred_count == 1
    seed(harness, batch_state(members=[finding("active", path="src/other.py")], status="approved"))
    result = sync(
        harness, [finding(), finding("active", path="src/other.py")], max_active_work_items=1
    )
    assert stored(harness).status == "capacity_deferred"
    assert not harness[0].open[1]
    assert result.capacity_deferred_count == 1


@pytest.mark.parametrize("kind", ["scope", "requirements"])
def test_invalid_selection_persists_blocker_before_reopening(harness, kind):
    original = batch_state(members=[finding("a"), finding("b")], status="capacity_deferred")
    seed(harness, original, is_open=False)
    changed = (
        finding("b", path="src/moved.py")
        if kind == "scope"
        else finding("b", constraints="different")
    )
    result = sync(harness, [finding("a"), changed])
    state = stored(harness)
    assert state.status == "blocked"
    assert state.batch.selection_failure.reason == f"batch_{kind}_mismatch"
    assert state.execution_failure is None
    assert state.policy_deferral is None and state.capacity_deferral is None
    assert state.batch.members == original.batch.members
    assert harness[0].open[1]
    assert result.selection_blocked_count == 1
    actions = [action for action, _ in harness[0].calls]
    assert actions.index("update") < actions.index("reopen")
    body = harness[1].upsert_service.renderer.render_body(state)
    assert "## Selection" in body
    assert "/zeroone remediation requeue" in body
    sync(harness, [finding("a"), finding("b")])
    assert stored(harness).status == "blocked"


@pytest.mark.parametrize(
    "status", ["blocked", "in_progress", "review_feedback_required", "review_revision_queued"]
)
def test_protected_work_only_refreshes_observations(harness, status):
    original = batch_state(
        status=status,
        linked_change_request=ChangeRequestRef(number=7, web_url="https://example/mr/7"),
    )
    seed(harness, original)
    result = sync(harness)
    state = stored(harness)
    assert state.status == status
    assert state.linked_change_request == original.linked_change_request
    assert state.batch.observations[0].last_confirmed_presence == "absent"
    assert result.no_longer_detected_count == 0


def test_manually_closed_safe_batch_is_history_not_automatically_reactivated(harness):
    old = batch_state(status="approved")
    seed(harness, old, is_open=False)
    result = sync(harness, [finding()])
    assert stored(harness, 1) == old
    assert not harness[0].open[1]
    assert stored(harness, 2).work_item_id != old.work_item_id
    assert result.created_count == 1


def test_closed_protected_work_reserves_group(harness):
    seed(harness, batch_state(status="blocked"), is_open=False)
    result = sync(harness, [finding("new")])
    assert result.created_count == 0
    assert not harness[0].open[1]


@pytest.mark.parametrize("protection", ["claim", "history", "linked"])
def test_closed_protected_approved_batch_refreshes_without_reopening(harness, protection):
    evidence = {
        "claim": {"claim": WorkItemClaim(run_id="executing", claimed_at=NOW)},
        "history": {"attempt_number": 2},
        "linked": {
            "linked_change_request": ChangeRequestRef(number=7, web_url="https://example/mr/7")
        },
    }[protection]
    original = batch_state(status="approved", **evidence)
    seed(harness, original, is_open=False)

    result = sync(harness, [finding(), finding("new")])
    state = stored(harness)

    assert state.status == "approved"
    assert state.claim == original.claim
    assert state.attempt_number == original.attempt_number
    assert state.linked_change_request == original.linked_change_request
    assert state.batch.members == original.batch.members
    assert state.batch.observations[0].sync_run_id == "current"
    assert not harness[0].open[1]
    assert ("update", 1) in harness[0].calls
    assert ("reopen", 1) not in harness[0].calls
    assert result.created_count == 0
    assert result.policy_reactivated_count == 0


def test_dismissed_members_do_not_consume_capacity(harness):
    seed(harness, batch_state(status="dismissed"), is_open=False)
    result = sync(harness, [finding(), finding("b")], max_active_work_items=1)
    assert [m.finding_id for m in stored(harness, 2).batch.members] == ["b"]
    assert result.backlog_reason_counts["dismissed"] == 1


def test_reopened_duplicate_ownership_warns_without_writing(harness, caplog):
    seed(harness, batch_state())
    seed(harness, batch_state())
    before = dict(harness[0].issues)
    result = sync(harness, [finding()])
    assert harness[0].issues == before
    assert result.promoted_count == 0
    assert result.projection_warning_count == 1
    assert "ownership is ambiguous" in caplog.text


def test_read_before_write_preserves_late_claim(harness):
    seed(harness, batch_state())

    def claim(number):
        state = harness[1].lookup_service.parser.parse_work_item_state(
            harness[0].issues[number].body
            if harness[0].provider == "github"
            else harness[0].issues[number].description
        )
        state.claim = WorkItemClaim(claimed_at=NOW, run_id="other")
        renderer = harness[1].upsert_service.renderer
        body = "body" if harness[0].provider == "github" else "description"
        harness[0]._store(
            number,
            dict(
                title=renderer.render_title(state),
                labels=renderer.render_labels(state),
                **{body: renderer.render_body(state)},
            ),
            True,
        )

    harness[0].on_get = claim
    result = sync(harness, [finding()])
    assert stored(harness).claim.run_id == "other"
    assert result.projection_warning_count == 1
    assert not any(action == "update" for action, _ in harness[0].calls)


def test_late_dismissal_prevents_batch_creation(harness):
    def dismiss(client):
        if len(client.queries) == 11:
            seed(harness, batch_state(status="dismissed"), is_open=False)

    harness[0].on_list = dismiss
    result = sync(harness, [finding()])
    assert harness[0].create_attempts == 0
    assert result.created_count == 0
    assert result.projection_warning_count == 1
    assert result.backlog_reason_counts["dismissed"] == 1


@pytest.mark.parametrize("failure", ["create_before", "create_after"])
def test_uncertain_creation_never_blindly_retries(harness, failure):
    harness[0].fail = failure
    result = sync(harness, [finding()])
    assert harness[0].create_attempts == 1
    assert result.projection_warning_count == 1
    assert result.promoted_count == (failure == "create_after")
    assert any("zeroone-batch:" in label for _, labels in harness[0].queries for label in labels)


@pytest.mark.parametrize("failure", ["update", "close", "reopen", "get"])
def test_projection_failure_is_nonfatal_and_other_groups_continue(harness, failure):
    seed(
        harness,
        batch_state(status="capacity_deferred" if failure == "reopen" else "candidate"),
        is_open=failure != "reopen",
    )
    harness[0].fail = failure
    findings = [finding()] if failure == "reopen" else []
    result = sync(harness, [*findings, finding("other", path="src/other.py")])
    assert result.projection_warning_count >= 1
    assert result.created_count == 1


def test_missing_ownership_inventory_never_creates_work(harness):
    harness[0].fail = "list"
    with pytest.raises(RuntimeError):
        sync(harness, [finding()])
    assert harness[0].create_attempts == 0


def test_dry_run_previews_freed_capacity_without_clock_identity_or_writes(harness):
    seed(harness, batch_state(status="approved"))
    before = dict(harness[0].issues)
    clock = Mock(side_effect=AssertionError("clock invoked"))
    with patch(
        "zeroone_ops.services.control_plane.work_items.batch_finding_creation_service.create_finding_batch_identity",
        side_effect=AssertionError("identity allocated"),
    ):
        result = FindingSyncCoordinator(harness[2], clock=clock).sync(
            repository_scope=SCOPE,
            findings=[finding("new", path="src/new.py")],
            policy_state=policy(),
            managed_source_ids={"ruff-sarif"},
            max_active_work_items=1,
            persist=False,
        )
    clock.assert_not_called()
    assert result.no_longer_detected_count == 1
    assert result.selected_member_count == 1
    assert harness[0].issues == before
    assert all(action == "get" for action, _ in harness[0].calls)
    assert harness[0].create_attempts == 0


def test_deployed_sync_creates_a_batch_and_intake_admits_it(harness):
    client, service, _ = harness
    sync_service = (
        GitHubFindingSyncService(work_item_service=service)
        if client.provider == "github"
        else GitLabFindingSyncService(work_item_service=service)
    )
    scope = {"repository_id" if client.provider == "github" else "project_id": SCOPE}
    result = sync_service.sync(**scope, findings=[finding(), finding("b")], policy_state=policy())
    assert result.created_count == 1
    assert result.selected_member_count == 2
    assert len(stored(harness).batch.members) == 2
    assert is_remediation_execution_eligible(stored(harness))


def test_unknown_grouping_keeps_single_finding_identity(harness):
    result = sync(harness, [finding(rule=None)])
    assert result.created_count == 1
    assert stored(harness).batch is None
    assert stored(harness).source.source_item_key == "a"


def test_source_priority_and_existing_single_work_stay_independent(harness):
    single = batch_state(status="candidate").model_copy(
        update={"batch": None, "work_item_id": "single"}
    )
    single.source = single.source.model_copy(update={"source_item_key": "a"})
    seed(harness, single)
    result = sync(
        harness,
        [finding(), finding("important", source="semgrep-sarif", path="src/security.py")],
        source_priorities={"semgrep-sarif": 1},
        max_active_work_items=1,
    )
    assert stored(harness, 1).batch is None
    assert stored(harness, 1).status == "capacity_deferred"
    assert stored(harness, 2).source.source == "semgrep-sarif"
    assert result.created_count == 1


@pytest.mark.parametrize("mode", ["omitted", "clear", "replace"])
def test_provider_upsert_preserves_omitted_batch_and_honors_explicit_values(harness, mode):
    original = batch_state(status="approved")
    seed(harness, original)
    payload = original.model_dump(exclude={"batch"})
    if mode == "clear":
        payload["batch"] = None
    elif mode == "replace":
        payload["batch"] = original.batch.model_dump()
        payload["batch"]["observations"][0]["freshness"] = "unknown"
    incoming = WorkItemState.model_validate(payload)
    if harness[0].provider == "github":
        result = harness[1].upsert_work_item(repository_id=SCOPE, work_item=incoming)
    else:
        result = harness[1].upsert_work_item(project_id=SCOPE, work_item=incoming)
    assert result.work_item.batch == (original.batch if mode == "omitted" else incoming.batch)
    assert stored(harness).batch == result.work_item.batch


def test_closed_discovery_uses_status_indexes_not_general_history(harness):
    seed(harness, batch_state(status="blocked"), is_open=False)
    harness[2].load_inventory(repository_scope=SCOPE)
    closed = [labels for is_open, labels in harness[0].queries if not is_open]
    assert closed
    assert all(len(labels) == 2 and labels[1].startswith("zeroone-status:") for labels in closed)


def test_exact_id_rediscovery_keeps_closed_batch_authority(harness):
    original = batch_state(status="dismissed")
    seed(harness, original, is_open=False)
    matches = harness[2].rediscover_batch(
        repository_scope=SCOPE, work_item_id=original.work_item_id
    )
    assert len(matches) == 1 and not matches[0].is_open
    assert matches[0].work_item == original
    assert all(labels[1].startswith("zeroone-batch:") for _, labels in harness[0].queries)


def test_malformed_indexed_authority_stops_creation(harness):
    seed(harness, batch_state())
    body = "body" if harness[0].provider == "github" else "description"
    harness[0].issues[1] = harness[0].issues[1].model_copy(update={body: "not machine state"})
    with pytest.raises(ValueError, match="ownership inventory"):
        sync(harness, [finding("b")])
    assert harness[0].create_attempts == 0


def test_dry_run_selection_blocker_matches_live_reason_without_writes(harness):
    seed(
        harness,
        batch_state(members=[finding("a"), finding("b")], status="capacity_deferred"),
        is_open=False,
    )
    before = dict(harness[0].issues)
    result = sync(harness, [finding("a"), finding("b", constraints="Different")], persist=False)
    assert result.selection_blocked_count == 1
    assert result.backlog_reason_counts["batch_requirements_mismatch"] == 2
    assert harness[0].issues == before
    assert not harness[0].open[1]


def test_selection_failure_evidence_is_bounded_and_safely_rendered(harness):
    identifiers = ["a`\n## injected", *[f"member-{number:02}" for number in range(12)]]
    original = batch_state(
        members=[finding(key) for key in identifiers], status="capacity_deferred"
    )
    seed(harness, original, is_open=False)
    sync(
        harness,
        [
            finding(key, constraints="Different" if index else "Original")
            for index, key in enumerate(identifiers)
        ],
    )
    state = stored(harness)
    failure = state.batch.selection_failure
    assert len(failure.member_ids) == 10
    assert failure.omitted_member_count == 3
    body = harness[1].upsert_service.renderer.render_body(state)
    assert "\n## injected\n" not in body
    assert "and 3 more members" in body
    assert state.execution_failure is None


def test_partial_close_failure_can_be_repaired_without_repromotion(harness):
    seed(harness, batch_state())
    harness[0].fail = "close"
    result = sync(harness)
    assert result.projection_warning_count == 1
    assert stored(harness).status == "completed"
    assert harness[0].open[1]
    harness[0].fail = None
    sync(harness)
    assert not harness[0].open[1]


def test_dismissal_filter_precedes_requirement_compatibility(harness):
    seed(harness, batch_state(members=[finding("a"), finding("b")]))
    seed(harness, batch_state(members=[finding("b")], status="dismissed"), is_open=False)
    result = sync(harness, [finding("a"), finding("b", constraints="Different")])
    assert stored(harness).status == "approved"
    assert result.selected_member_count == 1
    assert result.selection_blocked_count == 0


def test_uncertain_duplicate_identity_stops_without_another_create(harness):
    harness[0].fail = "create_duplicate"
    result = sync(harness, [finding()])
    assert harness[0].create_attempts == 1
    assert len(harness[0].issues) == 2
    assert result.promoted_count == 0
    assert result.projection_warning_count == 1


def test_native_closure_after_selection_is_not_overwritten(harness):
    seed(harness, batch_state())
    harness[0].on_get = lambda number: harness[0].open.update({number: False})
    result = sync(harness, [finding()])
    assert not harness[0].open[1]
    assert result.promoted_count == 0
    assert result.projection_warning_count == 1
    assert all(action == "get" for action, _ in harness[0].calls)


def test_failed_blocker_reopen_is_repaired_without_unblocking(harness):
    seed(
        harness,
        batch_state(members=[finding("a"), finding("b")], status="capacity_deferred"),
        is_open=False,
    )
    harness[0].fail = "reopen"
    result = sync(harness, [finding("a"), finding("b", constraints="Different")])
    assert result.projection_warning_count == 1
    assert stored(harness).status == "blocked"
    assert not harness[0].open[1]
    harness[0].fail = None
    sync(harness, [finding("a"), finding("b")])
    assert stored(harness).status == "blocked"
    assert harness[0].open[1]


def test_limit_one_and_current_priority_are_respected(harness):
    result = sync(harness, [finding("a"), finding("b")], max_findings_per_work_item=1)
    assert result.created_count == 1
    assert len(stored(harness).batch.members) == 1

    deferred = batch_state(
        members=[finding("c", severity="high", path="src/other.py")], status="capacity_deferred"
    )
    seed(harness, deferred, is_open=False)
    result = sync(harness, [finding("a"), finding("c", severity="low", path="src/other.py")])
    assert stored(harness, 2).severity == "low"
    assert result.policy_reactivated_count == 1


def test_conflicting_owners_are_not_resolved_by_complete_absence(harness):
    seed(harness, batch_state(status="approved"))
    seed(harness, batch_state(status="approved"))
    before = dict(harness[0].issues)
    result = sync(harness)
    assert result.projection_warning_count == 1
    assert harness[0].issues == before
    assert all(harness[0].open.values())


def test_history_bearing_candidate_retains_ownership_without_selection(harness):
    seed(harness, batch_state(attempt_number=2))
    result = sync(
        harness, [finding(), finding("other", path="src/other.py")], max_active_work_items=1
    )
    assert stored(harness).status == "candidate"
    assert stored(harness).attempt_number == 2
    assert stored(harness, 2).status == "approved"
    assert result.selected_member_count == 1


def test_observation_refresh_preserves_all_execution_owned_evidence(harness):
    original = WorkItemState.model_validate(
        batch_state(status="blocked").model_dump()
        | {
            "claim": {"claimed_at": NOW, "run_id": "execution"},
            "execution_failure": {
                "stage": "validation",
                "summary": "Earlier failure",
                "retry_count": 1,
                "run_id": "execution",
                "occurred_at": NOW,
            },
            "publication_retry": {
                "branch_name": "zeroone/fix",
                "commit_sha": "abc",
                "reason": "change_request_publish_failed",
            },
            "semantic_safety": {"rejection_reason": "Preserve evidence"},
            "projected_review": {
                "classification": "manual_review_only",
                "reviewed_sha": "abc",
                "follow_up_required": False,
            },
            "last_revision_command": {
                "actor": "operator",
                "request_reference": "note-1",
                "occurred_at": NOW,
                "reviewed_sha": "abc",
            },
            "attempt_number": 2,
        }
    )
    seed(harness, original)
    sync(harness)
    state = stored(harness)
    assert state.model_dump(exclude={"batch"}) == original.model_dump(exclude={"batch"})
    assert state.batch.members == original.batch.members
    assert state.batch.observations[0].last_confirmed_presence == "absent"
