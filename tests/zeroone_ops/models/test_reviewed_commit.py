"""Validate optional commit presentation without changing historical identities."""

import pytest
from pydantic import ValidationError

from zeroone_ops.models.review_overview import ReviewOverviewEnvelope
from zeroone_ops.models.reviewed_commit import ReviewedCommitMetadata


@pytest.mark.parametrize("title", ["", " ", " padded", "padded ", "first\nsecond", "x" * 301])
def test_metadata_rejects_unbounded_or_multiline_stored_titles(title: str) -> None:
    with pytest.raises(ValidationError):
        ReviewedCommitMetadata(head_sha="historical-sha", title=title)


def test_commit_metadata_is_frozen_and_accepts_existing_identity_shapes() -> None:
    metadata = ReviewedCommitMetadata(head_sha="historical-sha", title="x" * 300)
    assert metadata.title == "x" * 300
    with pytest.raises(ValidationError, match="frozen"):
        metadata.title = "replacement"


@pytest.mark.parametrize("records", ["complete_passes", "history"])
def test_metadata_must_match_owning_head(
    overview_envelope: ReviewOverviewEnvelope, records: str
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    payload[records][0]["reviewed_commit"] = {"head_sha": "another-head", "title": "Wrong commit"}
    with pytest.raises(ValidationError, match="metadata must match"):
        ReviewOverviewEnvelope.model_validate(payload)


def test_commit_metadata_is_retained_in_summaries_and_round_trips(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    for record in (payload["complete_passes"][0], payload["history"][0]):
        record["reviewed_commit"] = {"head_sha": record["head_sha"], "title": "Fix reviewed commit"}
    envelope = ReviewOverviewEnvelope.model_validate(payload)

    assert envelope.complete_passes[0].summary() == envelope.history[0]
    assert ReviewOverviewEnvelope.model_validate_json(envelope.model_dump_json()) == envelope
    payload["history"][0]["reviewed_commit"]["title"] = "Different label"
    with pytest.raises(ValidationError, match="match their history"):
        ReviewOverviewEnvelope.model_validate(payload)


def test_historical_envelopes_have_no_manufactured_metadata(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    payload = overview_envelope.model_dump(mode="json")
    for record in [*payload["complete_passes"], *payload["history"]]:
        record.pop("reviewed_commit")
    restored = ReviewOverviewEnvelope.model_validate(payload)
    assert all(
        record.reviewed_commit is None for record in [*restored.complete_passes, *restored.history]
    )
