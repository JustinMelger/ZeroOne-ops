from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from zeroone_ops.models.config import RemediationConfig
from zeroone_ops.models.finding import FindingSourceMetadata, NormalizedFinding, RemediationContext
from zeroone_ops.models.finding_batch import (
    BatchMemberObservation,
    FindingBatchGroup,
    WorkItemBatch,
)
from zeroone_ops.models.finding_batch_snapshot import BatchFindingSnapshot
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.intake.finding_batch_identity import create_finding_batch_identity


def _finding(identifier="a", **changes):
    return NormalizedFinding(
        finding_id=identifier,
        source_id="ruff-sarif",
        severity="medium",
        title="Unused import",
        summary="Unused import: os",
        repository_path="src/routes.py",
        remediation_context=RemediationContext(
            category="static_analysis_fix", diagnostic_code="F401"
        ),
    ).model_copy(update=changes)


def _observation(identifier="a", **changes):
    return BatchMemberObservation(
        finding_id=identifier,
        last_confirmed_presence="detected",
        freshness="current",
        sync_run_id="sync-1",
        observed_at=datetime(2026, 10, 17, tzinfo=UTC),
        last_confirmed_sync_run_id="sync-1",
        last_confirmed_finding=_finding(identifier),
    ).model_copy(update=changes)


def _batch(**changes):
    fields = {
        "group": FindingBatchGroup(
            repository_scope="team/repo",
            file_path="src/routes.py",
            source_id="ruff-sarif",
            rule_id="F401",
        ),
        "members": (_finding(),),
        "observations": (_observation(),),
    }
    return WorkItemBatch(**(fields | changes))


def _state(batch=None, **changes):
    identity = create_finding_batch_identity()
    fields = {
        "work_item_id": identity.work_item_id,
        "kind": "remediation",
        "status": "approved",
        "source": WorkItemSourceRef(
            source="ruff-sarif",
            source_item_key=identity.source_item_key,
            repository_scope="team/repo",
        ),
        "summary": "F401 batch",
        "severity": "medium",
        "file_path": "src/routes.py",
        "remediation_context": RemediationContext(diagnostic_code="F401"),
        "batch": batch,
    }
    return WorkItemState(**(fields | changes))


@pytest.mark.parametrize("value", [0, -1, True, False, "10", 1.5, None])
def test_batch_limit_is_strict_positive_integer(value):
    with pytest.raises(ValidationError):
        RemediationConfig(max_findings_per_work_item=value)


def test_batch_limit_defaults_to_ten_and_accepts_one():
    assert RemediationConfig().max_findings_per_work_item == 10
    assert RemediationConfig(max_findings_per_work_item=1).max_findings_per_work_item == 1


@pytest.mark.parametrize(
    "path", ["", "/tmp/file", "../file", "src/../file", "./file", "a//b", "C:/file", "a\\b"]
)
def test_batch_group_requires_canonical_repository_path(path):
    with pytest.raises(ValidationError):
        FindingBatchGroup(
            repository_scope="team/repo", file_path=path, source_id="ruff-sarif", rule_id="F401"
        )


@pytest.mark.parametrize("field", ["repository_scope", "source_id", "rule_id"])
def test_batch_group_rejects_blank_scope(field):
    fields = dict(
        repository_scope="team/repo",
        file_path="src/routes.py",
        source_id="ruff-sarif",
        rule_id="F401",
    )
    with pytest.raises(ValidationError):
        FindingBatchGroup(**(fields | {field: " "}))


@pytest.mark.parametrize(
    "changes",
    [
        {"members": ()},
        {"members": (_finding(), _finding())},
        {"observations": ()},
        {"observations": (_observation(), _observation())},
        {"observations": (_observation("other"),)},
        {"members": (_finding(source_id="mypy-sarif"),)},
        {"members": (_finding(repository_path="src/other.py"),)},
        {"members": (_finding(remediation_context=RemediationContext(diagnostic_code="F821")),)},
        {"observations": (_observation(last_confirmed_finding=_finding("other")),)},
        {"observations": (_observation(last_confirmed_finding=_finding(source_id="other")),)},
    ],
)
def test_batch_requires_complete_consistent_membership(changes):
    with pytest.raises(ValidationError):
        _batch(**changes)


def test_batch_defensively_copies_original_and_observation_evidence():
    original = _finding()
    evidence = _finding()
    observation = _observation(last_confirmed_finding=evidence)
    batch = _batch(members=(original,), observations=(observation,))
    original.summary = "changed"
    evidence.summary = "changed"
    observation.last_confirmed_finding.summary = "also changed"
    assert batch.members[0].summary == "Unused import: os"
    assert batch.observations[0].last_confirmed_finding.summary == "Unused import: os"
    with pytest.raises(ValidationError):
        batch.members = ()


def test_batch_identity_is_explicit_and_has_no_predecessor():
    identity = create_finding_batch_identity()
    identifier = identity.work_item_id.removeprefix("work-")
    assert UUID(identifier).version == 4
    assert identity.source_item_key == f"batch-v1:{identifier}"
    assert create_finding_batch_identity() != identity
    with pytest.raises(FrozenInstanceError):
        identity.work_item_id = "changed"
    state = _state(_batch())
    restored = WorkItemState.model_validate_json(state.model_dump_json())
    assert restored == state
    assert restored.identity_key == state.identity_key
    assert "generation_parent_id" not in restored.batch.model_dump()


@pytest.mark.parametrize(
    "changes",
    [
        {"work_item_id": "work-not-a-uuid"},
        {"file_path": "src/other.py"},
        {
            "source": WorkItemSourceRef(
                source="ruff-sarif", source_item_key="a", repository_scope="team/repo"
            )
        },
        {"remediation_context": RemediationContext(diagnostic_code="other")},
    ],
)
def test_work_item_validates_only_explicit_batch_scope(changes):
    with pytest.raises(ValidationError):
        _state(_batch(), **changes)


def test_historical_single_finding_state_remains_compatible():
    historical = dict(
        work_item_id="old-arbitrary-id",
        kind="remediation",
        status="candidate",
        source=dict(source="sonarqube", source_item_key="sonar-key"),
        summary="Old issue",
    )
    state = WorkItemState.model_validate(historical)
    assert state.batch is None
    assert state.identity_key == ("sonarqube", "sonar-key", None, "remediation")
    assert "batch" not in state.model_dump(exclude_none=True)


def test_batch_member_identity_cannot_be_blank():
    with pytest.raises(ValidationError, match="must not be blank"):
        _batch(members=(_finding(" "),), observations=(_observation(" "),))


def test_batch_state_defensively_copies_supplied_batch():
    batch = _batch()
    state = _state(batch)
    with pytest.raises(ValidationError, match="frozen"):
        batch.members[0].summary = "external mutation"
    assert state.batch.members[0].summary == "Unused import: os"


@pytest.mark.parametrize("observation_evidence", [False, True])
@pytest.mark.parametrize("field", ["finding_id", "source_id", "repository_path"])
def test_batch_scope_snapshots_reject_direct_mutation(observation_evidence, field):
    batch = _batch()
    member = (
        batch.observations[0].last_confirmed_finding if observation_evidence else batch.members[0]
    )
    before = batch.model_dump_json()
    with pytest.raises(ValidationError, match="frozen"):
        setattr(member, field, "changed")
    assert batch.model_dump_json() == before


@pytest.mark.parametrize("observation_evidence", [False, True])
def test_nested_batch_requirements_are_immutable(observation_evidence):
    finding = _finding()
    finding.remediation_context.validation_commands = ["pytest"]
    finding.remediation_context.acceptance_criteria = ["Preserve behavior"]
    batch = _batch(members=(finding,), observations=(_observation(last_confirmed_finding=finding),))
    member = (
        batch.observations[0].last_confirmed_finding if observation_evidence else batch.members[0]
    )
    before = batch.model_dump_json()
    with pytest.raises(ValidationError, match="frozen"):
        member.remediation_context.diagnostic_code = "F821"
    with pytest.raises(ValidationError, match="frozen"):
        member.remediation_context.constraints = "Changed"
    with pytest.raises(AttributeError):
        member.remediation_context.validation_commands.append("modified")
    with pytest.raises(TypeError):
        member.remediation_context.acceptance_criteria[0] = "modified"
    assert batch.model_dump_json() == before


def test_batch_provenance_is_recursively_immutable_and_round_trips():
    finding = _finding(
        source_metadata=FindingSourceMetadata(
            native_id="scanner-key",
            source_url="https://example/finding",
            attributes={
                "tool": "Ruff",
                "fingerprints": {"primary": "abc"},
                "tags": ["lint", {"name": "quality"}],
                "score": 0.5,
                "enabled": True,
            },
        )
    )
    batch = _batch(members=(finding,), observations=(_observation(last_confirmed_finding=finding),))
    before = batch.model_dump_json()
    for member in (batch.members[0], batch.observations[0].last_confirmed_finding):
        metadata = member.source_metadata
        with pytest.raises(ValidationError, match="frozen"):
            metadata.native_id = "changed"
        with pytest.raises(TypeError):
            metadata.attributes["tool"] = "changed"
        with pytest.raises(TypeError):
            metadata.attributes["fingerprints"]["primary"] = "changed"
        with pytest.raises(TypeError):
            metadata.attributes["tags"][1]["name"] = "changed"
        with pytest.raises(AttributeError):
            metadata.attributes["tags"].append("changed")
        assert member.to_finding() == finding
    finding.source_metadata.attributes["fingerprints"]["primary"] = "external"
    assert batch.model_dump_json() == before
    assert WorkItemBatch.model_validate_json(before) == batch
    state = _state(batch)
    assert WorkItemState.model_validate_json(state.model_dump_json()) == state
    assert state.model_copy(deep=True) == state


def test_materialized_finding_is_an_isolated_mutable_copy():
    snapshot = BatchFindingSnapshot.model_validate(_finding())
    finding = snapshot.to_finding()
    finding.repository_path = "other.py"
    finding.remediation_context.diagnostic_code = "other"
    finding.remediation_context.validation_commands.append("pytest")
    assert snapshot.repository_path == "src/routes.py"
    assert snapshot.remediation_context.diagnostic_code == "F401"
    assert snapshot.remediation_context.validation_commands == ()


def test_observation_replacement_is_validated_without_mutating_original_members():
    batch = _batch()
    before = batch.model_dump_json()
    refreshed = _finding(severity="high")
    observation = BatchMemberObservation.model_validate(
        batch.observations[0].model_dump() | {"last_confirmed_finding": refreshed}
    )
    replacement = WorkItemBatch.model_validate(
        batch.model_dump() | {"observations": (observation,)}
    )
    assert replacement.members[0].severity == "medium"
    assert replacement.observations[0].last_confirmed_finding.severity == "high"
    assert batch.model_dump_json() == before
    changed_scope = _finding(repository_path="other.py")
    observation = BatchMemberObservation.model_validate(
        observation.model_dump() | {"last_confirmed_finding": changed_scope}
    )
    with pytest.raises(ValidationError, match="source, file, and rule"):
        WorkItemBatch.model_validate(batch.model_dump() | {"observations": (observation,)})


def test_copy_updates_cannot_reintroduce_mutable_nested_evidence():
    snapshot = BatchFindingSnapshot.model_validate(_finding())
    context = RemediationContext(diagnostic_code="F401", validation_commands=["pytest"])
    replacement = snapshot.model_copy(update={"remediation_context": context}, deep=True)
    context.validation_commands.append("changed")
    assert replacement.remediation_context.validation_commands == ("pytest",)
    with pytest.raises(ValidationError, match="frozen"):
        replacement.remediation_context.diagnostic_code = "other"


@pytest.mark.parametrize("attributes", [{"bad": object()}, {"nested": {1: "bad key"}}])
def test_snapshot_provenance_requires_json_compatible_values(attributes):
    with pytest.raises(ValidationError, match="Batch provenance"):
        BatchFindingSnapshot.model_validate(
            _finding(source_metadata=FindingSourceMetadata(attributes=attributes))
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": "arbitrary"},
        {"member_ids": []},
        {"member_ids": ["not-a-member"]},
        {"member_ids": ["a", "a"]},
        {"member_ids": ["a"] * 11},
        {"omitted_member_count": -1},
    ],
)
def test_selection_failure_evidence_rejects_invalid_or_unbounded_references(changes):
    batch = _batch()
    failure = (
        dict(
            reason="batch_scope_mismatch",
            member_ids=["a"],
            run_id="run",
            occurred_at=datetime(2026, 10, 18, tzinfo=UTC),
        )
        | changes
    )
    with pytest.raises(ValidationError):
        WorkItemBatch.model_validate(batch.model_dump() | {"selection_failure": failure})
