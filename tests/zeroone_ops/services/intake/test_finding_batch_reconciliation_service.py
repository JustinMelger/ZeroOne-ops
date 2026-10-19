"""Exercise batch reconciliation as pure decisions without provider orchestration."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import patch

from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.finding_batch import WorkItemBatch
from zeroone_ops.models.finding_batch_sync import BatchSyncContext
from zeroone_ops.models.finding_sync import FindingSyncRecord
from zeroone_ops.models.policy import PolicySeverityStateEntry, PolicyState
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.intake.finding_batch_identity import create_finding_batch_identity
from zeroone_ops.services.intake.finding_batch_ownership import finding_batch_group
from zeroone_ops.services.intake.finding_batch_reconciliation_service import (
    FindingBatchReconciliationService,
)

NOW = datetime(2026, 10, 18, tzinfo=UTC)
SCOPE = "team/repo"


def _finding(identifier="a", *, path="src/routes.py", severity="medium"):
    return NormalizedFinding(
        finding_id=identifier,
        source_id="ruff-sarif",
        severity=severity,
        repository_path=path,
        title="Unused import",
        summary="Unused import os",
        remediation_context=RemediationContext(
            category="static_analysis_fix", diagnostic_code="F401"
        ),
    )


def _policy(*severities):
    return PolicyState(
        severity_policy=[
            PolicySeverityStateEntry(severity=severity, enabled=True)
            for severity in severities or ("high", "medium", "low")
        ]
    )


def _record(*, members=None, status="candidate", **changes):
    members = members or (_finding(),)
    first = members[0]
    identity = create_finding_batch_identity()
    batch = WorkItemBatch.model_validate(
        dict(
            group=finding_batch_group(repository_scope=SCOPE, finding=first),
            members=members,
            observations=[
                dict(
                    finding_id=member.finding_id,
                    last_confirmed_presence="detected",
                    freshness="current",
                    sync_run_id="old",
                    observed_at=NOW,
                    last_confirmed_finding=member,
                )
                for member in members
            ],
        )
    )
    state = WorkItemState(
        work_item_id=identity.work_item_id,
        kind="remediation",
        status=status,
        source=WorkItemSourceRef(
            source=first.source_id, source_item_key=identity.source_item_key, repository_scope=SCOPE
        ),
        file_path=first.repository_path,
        summary="Batch",
        severity=first.severity,
        remediation_context=first.remediation_context,
        batch=batch,
        **changes,
    )
    return FindingSyncRecord(state, 1, "https://example/issues/1", True)


def context(**changes):
    return BatchSyncContext(
        **(dict(repository_scope=SCOPE, policy_state=_policy(), run_id="new", now=NOW) | changes)
    )


def test_pure_reconciliation_returns_scope_decision_without_mutating_inputs():
    original = _record(members=(_finding("a"), _finding("b")))
    findings = {("ruff-sarif", "a"): _finding("a", path="src/moved.py")}
    before_state = original.work_item.model_dump_json()
    before_finding = findings[("ruff-sarif", "a")].model_dump_json()

    with (
        patch("time.time", side_effect=AssertionError("clock read")),
        patch("uuid.uuid4", side_effect=AssertionError("identity allocated")),
    ):
        outcome = FindingBatchReconciliationService().prepare(
            original, findings, {"ruff-sarif"}, context(), frozenset()
        )

    assert outcome.selection_reason == "batch_scope_mismatch"
    assert outcome.work_item.status == "blocked"
    assert outcome.work_item.batch.members == original.work_item.batch.members
    assert outcome.work_item.batch.observations[0].freshness == "unknown"
    assert original.work_item.model_dump_json() == before_state
    assert findings[("ruff-sarif", "a")].model_dump_json() == before_finding


def test_pure_refresh_retains_absence_on_unavailable_inventory():
    service = FindingBatchReconciliationService()
    original = _record(members=(_finding("a"), _finding("b")))
    complete = service.prepare(
        original, {("ruff-sarif", "a"): _finding("a")}, {"ruff-sarif"}, context(), frozenset()
    )
    unavailable = service.prepare(
        replace(original, work_item=complete.work_item), {}, set(), context(), frozenset()
    )

    assert [o.last_confirmed_presence for o in unavailable.work_item.batch.observations] == [
        "detected",
        "absent",
    ]
    assert all(o.freshness == "unknown" for o in unavailable.work_item.batch.observations)
    selected = service.capacity_state(unavailable, True, context())
    assert selected.status == "approved"
    assert len(selected.batch.members) == 2
    assert unavailable.work_item.status == "candidate"


def test_dry_run_policy_decision_does_not_manufacture_persistence_evidence():
    service = FindingBatchReconciliationService()
    original = _record(members=(_finding(severity="high"),))
    run = context(policy_state=_policy("medium"), now=None, persist=False)
    outcome = service.prepare(
        original, {("ruff-sarif", "a"): _finding(severity="high")}, {"ruff-sarif"}, run, frozenset()
    )

    assert outcome.work_item.status == "policy_deferred"
    assert outcome.work_item.policy_deferral is None
    assert not outcome.capacity_eligible
    assert service.capacity_state(outcome, False, run).status == "policy_deferred"


def test_pure_reconciliation_preserves_protected_work():
    original = _record(status="blocked", attempt_number=2)
    outcome = FindingBatchReconciliationService().prepare(
        original, {}, {"ruff-sarif"}, context(), frozenset()
    )
    assert not outcome.reconcilable
    assert outcome.work_item.status == "blocked"
    assert outcome.work_item.attempt_number == 2
    assert outcome.work_item.batch.observations[0].last_confirmed_presence == "absent"
