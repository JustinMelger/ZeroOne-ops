from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from zeroone_ops.models.config import RemediationConfig
from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.finding_batch import (
    BatchMemberObservation,
    FindingBatchGroup,
    WorkItemBatch,
)
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
    batch.members[0].summary = "external mutation"
    assert state.batch.members[0].summary == "Unused import: os"
