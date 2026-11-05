import pytest
from pydantic import ValidationError

from zeroone_ops.models.config import ReviewConfig
from zeroone_ops.models.review_overview import ReviewOverviewEnvelope, ReviewOverviewPass


def test_summary_is_factual_without_copying_complete_evidence(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    snapshot = overview_envelope.complete_passes[0]
    summary = snapshot.summary()

    assert summary.pass_id == snapshot.pass_id
    assert summary.run_id == snapshot.run_id
    assert summary.head_sha == snapshot.head_sha
    assert summary.completed_at == snapshot.completed_at
    assert summary.sequence == snapshot.sequence
    assert summary.classification == snapshot.artifact.classification
    assert summary.findings_count == 3
    assert summary.workflow_url == snapshot.workflow_url
    assert "artifact" not in summary.model_dump()
    assert "projection_pending" not in summary.model_dump()
    assert "inline_decisions" not in summary.model_dump()


@pytest.mark.parametrize("context_retention", [0, 1, 2, 10])
def test_provider_retention_is_independent_of_model_context_retention(
    overview_envelope: ReviewOverviewEnvelope,
    context_retention: int,
) -> None:
    config = ReviewConfig(max_prior_review_passes=context_retention)
    restored = ReviewOverviewEnvelope.model_validate_json(overview_envelope.model_dump_json())

    assert config.max_prior_review_passes == context_retention
    assert len(restored.complete_passes) == 2
    assert len(restored.history) == 5
    assert all(len(snapshot.artifact.findings) == 3 for snapshot in restored.complete_passes)
    assert restored == overview_envelope


@pytest.mark.parametrize("complete_count,summary_count", [(1, 1), (1, 5), (2, 2), (2, 5)])
def test_summary_retention_does_not_manufacture_or_discard_complete_artifacts(
    overview_envelope: ReviewOverviewEnvelope,
    complete_count: int,
    summary_count: int,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    payload["complete_passes"] = payload["complete_passes"][:complete_count]
    payload["history"] = payload["history"][:summary_count]

    restored = ReviewOverviewEnvelope.model_validate(payload)

    assert len(restored.complete_passes) == complete_count
    assert len(restored.history) == summary_count
    assert restored.complete_passes == overview_envelope.complete_passes[:complete_count]
    assert restored.history == overview_envelope.history[:summary_count]


@pytest.mark.parametrize(
    "field,value",
    [
        ("platform", "bitbucket"),
        ("repository_id", ""),
        ("change_request_number", 0),
        ("schema_version", "zeroone/review-overview/v2"),
        ("note_id", 777),
    ],
)
def test_rejects_invalid_scope_and_unknown_transport_fields(
    overview_envelope: ReviewOverviewEnvelope,
    field: str,
    value: object,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError):
        ReviewOverviewEnvelope.model_validate(payload)


@pytest.mark.parametrize("records", ["complete_passes", "history"])
@pytest.mark.parametrize(
    "corruption", ["empty", "reversed", "duplicate_sequence", "duplicate_id", "overflow"]
)
def test_rejects_invalid_history_order_identity_and_retention(
    overview_envelope: ReviewOverviewEnvelope,
    records: str,
    corruption: str,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    rows = payload[records]
    if corruption == "empty":
        payload[records] = []
    elif corruption == "reversed":
        payload[records] = list(reversed(rows))
    elif corruption == "duplicate_sequence":
        rows[1]["sequence"] = rows[0]["sequence"]
    elif corruption == "duplicate_id":
        rows[1]["pass_id"] = rows[0]["pass_id"]
    else:
        rows.insert(0, {**rows[0], "sequence": 6, "pass_id": "overflow"})

    with pytest.raises(ValidationError):
        ReviewOverviewEnvelope.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", "other-run"),
        ("head_sha", "other-head"),
        ("sequence", 6),
        ("completed_at", "2026-11-06T12:30:00Z"),
        ("classification", "no_findings"),
        ("findings_count", 0),
        ("workflow_url", "https://github.com/acme/shop/actions/runs/999"),
    ],
)
def test_complete_snapshots_must_match_history_summaries(
    overview_envelope: ReviewOverviewEnvelope,
    field: str,
    value: object,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    payload["history"][0][field] = value

    with pytest.raises(ValidationError):
        ReviewOverviewEnvelope.model_validate(payload)


def test_latest_summary_requires_complete_snapshot(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    payload["complete_passes"] = payload["complete_passes"][1:]

    with pytest.raises(ValidationError, match="latest logical pass"):
        ReviewOverviewEnvelope.model_validate(payload)


@pytest.mark.parametrize("corruption", ["missing_summary", "naive_time", "different_diff_head"])
def test_rejects_missing_history_or_contradictory_pass_provenance(
    overview_envelope: ReviewOverviewEnvelope,
    corruption: str,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    if corruption == "missing_summary":
        payload["history"].pop(1)
        with pytest.raises(ValidationError, match="match their history summaries"):
            ReviewOverviewEnvelope.model_validate(payload)
    else:
        snapshot = payload["complete_passes"][0]
        if corruption == "naive_time":
            snapshot["completed_at"] = "2026-11-05T12:30:00"
        else:
            snapshot["diff_refs"]["head_sha"] = "different-head"
        with pytest.raises(ValidationError):
            ReviewOverviewPass.model_validate(snapshot)
