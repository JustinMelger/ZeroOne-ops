"""Exercise provider-neutral attempt scope and recovery precedence."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from zeroone_ops.models.batch_execution import BatchAnalysisCoverage, BatchAttemptEvidence
from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.finding_batch import BatchMemberObservation, WorkItemBatch
from zeroone_ops.models.policy import PolicySeverityStateEntry, PolicyState
from zeroone_ops.models.work_item import PublicationRetryState, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.intake.finding_batch_identity import create_finding_batch_identity
from zeroone_ops.services.intake.finding_batch_ownership import finding_batch_group
from zeroone_ops.services.remediation.batch_execution_scope_service import (
    BatchExecutionScopeService,
)

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def batch_work_item(*, count=2):
    identity = create_finding_batch_identity()
    members = [
        NormalizedFinding(
            finding_id=f"member-{i}",
            source_id="ruff-sarif",
            severity="medium",
            title="Unused import",
            summary=f"Remove import {i}",
            repository_path="src/service.py",
            line_start=i + 1,
            remediation_context=RemediationContext(
                category="static_analysis_fix", diagnostic_code="F401"
            ),
        )
        for i in range(count)
    ]
    batch = WorkItemBatch.model_validate(
        dict(
            group=finding_batch_group(repository_scope="team/repo", finding=members[0]),
            members=members,
            observations=[
                BatchMemberObservation(
                    finding_id=m.finding_id,
                    last_confirmed_presence="detected",
                    freshness="current",
                    sync_run_id="scan-1",
                    observed_at=NOW,
                )
                for m in members
            ],
        )
    )
    return WorkItemState(
        work_item_id=identity.work_item_id,
        kind="remediation",
        status="approved",
        source=WorkItemSourceRef(
            source="ruff-sarif",
            source_item_key=identity.source_item_key,
            repository_scope="team/repo",
        ),
        summary="Remove unused imports",
        file_path="src/service.py",
        line=1,
        severity="medium",
        remediation_context=members[0].remediation_context,
        batch=batch,
    )


def enabled_policy():
    return PolicyState(severity_policy=[PolicySeverityStateEntry(severity="medium", enabled=True)])


def attempted_work_item():
    state = batch_work_item()
    decision = BatchExecutionScopeService().resolve(state, enabled_policy(), run_id="execution")
    return state.model_copy(update={"batch_attempt": decision.attempt})


def with_presence(state, presences, *, freshness="current"):
    observations = tuple(
        o.model_copy(update={"last_confirmed_presence": presence, "freshness": freshness})
        for o, presence in zip(state.batch.observations, presences, strict=True)
    )
    return state.model_copy(
        update={
            "batch": WorkItemBatch.model_validate(
                state.batch.model_dump() | {"observations": observations}
            )
        }
    )


def test_scope_excludes_absent_but_keeps_detected_unknown_and_inputs_unchanged():
    original = with_presence(batch_work_item(), ["absent", "detected"], freshness="unknown")
    before = original.model_dump()
    decision = BatchExecutionScopeService().resolve(original, enabled_policy(), run_id="run")
    assert decision.disposition == "execute"
    assert [m.finding_id for m in decision.attempt.members] == ["member-1"]
    assert len(original.batch.members) == 2
    assert original.model_dump() == before


@pytest.mark.parametrize("freshness,expected", [("current", "all_absent"), ("unknown", "blocked")])
def test_absence_requires_confirmed_current_inventory(freshness, expected):
    state = with_presence(batch_work_item(), ["absent", "absent"], freshness=freshness)
    assert BatchExecutionScopeService().resolve(state, enabled_policy()).disposition == expected


def test_scope_blocks_excluded_and_incompatible_members():
    state = batch_work_item()
    assert BatchExecutionScopeService().resolve(state, PolicyState()).disposition == "blocked"
    changed = state.batch.members[1].model_copy(
        update={
            "remediation_context": {
                "category": "static_analysis_fix",
                "diagnostic_code": "F401",
                "constraints": "different",
            }
        }
    )
    observations = (
        state.batch.observations[0],
        state.batch.observations[1].model_copy(update={"last_confirmed_finding": changed}),
    )
    state = state.model_copy(
        update={
            "batch": WorkItemBatch.model_validate(
                state.batch.model_dump() | {"observations": observations}
            )
        }
    )
    decision = BatchExecutionScopeService().resolve(state, enabled_policy())
    assert decision.disposition == "blocked"
    assert "incompatible" in decision.reason


@pytest.mark.parametrize("mode", ["publication", "revision"])
def test_recorded_scope_precedes_absence_and_current_policy(mode):
    state = attempted_work_item()
    accepted = BatchAttemptEvidence.model_validate(
        state.batch_attempt.model_dump()
        | {
            "coverage": BatchAnalysisCoverage(addressable_ids=("member-0", "member-1")),
        }
    )
    state = with_presence(state, ["absent", "absent"])
    state = state.model_copy(update={"batch_attempt": accepted})
    if mode == "publication":
        state = state.model_copy(
            update={
                "publication_retry": PublicationRetryState(
                    branch_name="zeroone/chore/batch",
                    commit_sha="abc",
                    reason="change_request_publish_failed",
                    batch_attempt=accepted,
                )
            }
        )
    else:
        state = state.model_copy(update={"status": "review_revision_queued"})
    decision = BatchExecutionScopeService().resolve(state, PolicyState())
    assert decision.disposition == "execute"
    assert decision.attempt == accepted
    broken = state.model_copy(
        update={
            "batch_attempt": None,
            "publication_retry": None,
            "status": "review_revision_queued",
        }
    )
    assert BatchExecutionScopeService().resolve(broken, enabled_policy()).disposition == "blocked"


@pytest.mark.parametrize(
    "ids", [(), ("member-0",), ("foreign", "member-1"), ("member-0", "member-0", "member-1")]
)
def test_attempt_rejects_incomplete_duplicate_or_foreign_coverage(ids):
    attempt = attempted_work_item().batch_attempt
    with pytest.raises(ValidationError):
        BatchAttemptEvidence.model_validate(
            attempt.model_dump()
            | {
                "coverage": BatchAnalysisCoverage(addressable_ids=ids),
            }
        )


def test_attempt_is_immutable_and_machine_state_round_trips():
    state = attempted_work_item()
    restored = WorkItemState.model_validate_json(state.model_dump_json())
    assert restored == state
    with pytest.raises(ValidationError):
        restored.batch_attempt.run_id = "changed"
    with pytest.raises(ValidationError):
        restored.batch_attempt.members[0].repository_path = "other.py"
