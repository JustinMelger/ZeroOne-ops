"""Earlier concerns remain visible independently of current review meaning."""

from datetime import UTC, datetime
from typing import Literal

import pytest
from pydantic import ValidationError

from zeroone_ops.models.review import PriorReviewInlineComment, PublishableReviewArtifact
from zeroone_ops.models.review_change_summary import ReviewChangeSummary
from zeroone_ops.models.review_overview import (
    EarlierReviewFinding,
    EarlierReviewFindings,
    ReviewOverviewEnvelope,
    ReviewOverviewPass,
)
from zeroone_ops.services.review.publish.earlier_review_findings import collect_earlier_findings
from zeroone_ops.services.review.publish.review_overview_codec import (
    ReviewOverviewError,
    decode_overview,
)
from zeroone_ops.services.review.publish.review_overview_renderer import render_overview


def _next(
    previous: ReviewOverviewEnvelope, artifact: PublishableReviewArtifact
) -> ReviewOverviewEnvelope:
    sequence = previous.history[0].sequence + 1
    snapshot = ReviewOverviewPass(
        pass_id=f"pass-{sequence}",
        run_id=f"run-{sequence}",
        head_sha=f"head-{sequence}",
        sequence=sequence,
        completed_at=datetime.now(UTC),
        artifact=artifact,
    )
    return ReviewOverviewEnvelope(
        platform=previous.platform,
        repository_id=previous.repository_id,
        change_request_number=previous.change_request_number,
        complete_passes=[snapshot, previous.complete_passes[0]],
        history=[snapshot.summary(), *previous.history[:4]],
        earlier_findings=collect_earlier_findings(previous=previous, artifact=artifact),
    )


def _unlinked(envelope: ReviewOverviewEnvelope) -> ReviewOverviewEnvelope:
    payload = envelope.model_dump(mode="json")
    for snapshot in payload["complete_passes"]:
        for finding in snapshot["artifact"]["findings"]:
            finding["inline_comment"] = None
    payload.pop("earlier_findings")
    return ReviewOverviewEnvelope.model_validate(payload)


def test_concern_survives_clean_passes_and_reappearance_without_mutation(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    previous = _unlinked(overview_envelope)
    original = previous.model_dump(mode="json")
    clean = PublishableReviewArtifact(classification="no_findings", summary="Clear")
    expected = collect_earlier_findings(previous=previous, artifact=clean)
    assert len(expected.concerns) == 3
    assert expected.concerns[0].sequence == 5
    current = previous
    for _ in range(8):
        current = _next(current, clean)
        assert current.earlier_findings == expected
        assert current.complete_passes[0].artifact == clean
    reappearing = previous.complete_passes[0].artifact.model_copy(deep=True)
    active = _next(current, reappearing)
    assert not active.earlier_findings.concerns
    disappeared = _next(active, clean)
    assert len(disappeared.earlier_findings.concerns) == 3
    assert all(
        entry.sequence == active.history[0].sequence
        for entry in disappeared.earlier_findings.concerns
    )
    assert previous.model_dump(mode="json") == original
    assert "Earlier Findings" in render_overview(current)
    assert "Resolution not verified" in render_overview(current)


@pytest.mark.parametrize(
    "url,status,retained",
    [
        ("https://example.com/discussion/1", "published", False),
        (None, "published", True),
        ("javascript:alert(1)", "published", True),
        ("https://example.com/discussion/1", "shadow", True),
        ("https://[invalid", "published", True),
    ],
)
def test_only_usable_published_links_release_visibility(
    overview_envelope: ReviewOverviewEnvelope,
    url: str | None,
    status: Literal["published", "shadow"],
    retained: bool,
) -> None:
    previous = _unlinked(overview_envelope)
    first = previous.complete_passes[0].artifact.findings[0]
    first.inline_comment = PriorReviewInlineComment(
        comment_id="1", comment_url=url, status=status, anchor_file_path=first.file_path
    )
    clean = PublishableReviewArtifact(classification="no_findings", summary="Clear")
    archive = collect_earlier_findings(previous=previous, artifact=clean)
    assert (first.stable_identity in {entry.identity for entry in archive.concerns}) is retained


def test_ten_entry_retention_is_deterministic_and_eviction_is_not_recounted(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    previous = _unlinked(overview_envelope)
    template = previous.complete_passes[0].artifact.findings[0]
    previous.complete_passes[0].artifact.findings = [
        template.model_copy(deep=True, update={"stable_identity": f"concern-{index:02}"})
        for index in reversed(range(13))
    ]
    previous.history[0] = previous.complete_passes[0].summary()
    clean = PublishableReviewArtifact(classification="no_findings", summary="Clear")
    current = _next(previous, clean)
    # The older complete snapshot contributes three additional concerns on adoption.
    assert len(current.earlier_findings.concerns) == 10
    assert [entry.identity for entry in current.earlier_findings.concerns] == [
        f"concern-{index:02}" for index in range(10)
    ]
    assert current.earlier_findings.evicted_count == 6
    assert _next(current, clean).earlier_findings == current.earlier_findings
    assert "Retention eviction does not establish resolution" in render_overview(current)


def test_fallback_identity_deduplicates_without_fuzzy_matching(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    previous = _unlinked(overview_envelope)
    for snapshot in previous.complete_passes:
        for finding in snapshot.artifact.findings:
            finding.stable_identity = None
    clean = PublishableReviewArtifact(classification="no_findings", summary="Clear")
    archive = collect_earlier_findings(previous=previous, artifact=clean)
    assert len(archive.concerns) == 3
    assert all(entry.sequence == 5 for entry in archive.concerns)


def test_archive_defaults_validation_and_escaping(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    previous = _unlinked(overview_envelope)
    clean = PublishableReviewArtifact(classification="no_findings", summary="Clear")
    assert previous.earlier_findings == EarlierReviewFindings()
    current = _next(previous, clean)
    entry = current.earlier_findings.concerns[0]
    with pytest.raises(ValidationError, match="unique"):
        EarlierReviewFindings(concerns=(entry, entry))
    with pytest.raises(ValidationError):
        EarlierReviewFindings(evicted_count=-1)
    with pytest.raises(ValidationError):
        EarlierReviewFindings(
            concerns=tuple(
                entry.model_copy(update={"identity": f"finding-{index:02}"}) for index in range(11)
            )
        )
    with pytest.raises(ValidationError, match="descending"):
        EarlierReviewFindings(
            concerns=(
                entry.model_copy(update={"identity": "z"}),
                entry.model_copy(update={"identity": "a"}),
            )
        )
    hostile = entry.model_copy(deep=True)
    hostile.finding.evidence = "<script> <!-- zeroone:review-overview:v1 [click](javascript:bad)"
    current = current.model_copy(
        update={"earlier_findings": EarlierReviewFindings(concerns=(hostile,))}
    )
    body = render_overview(current)
    assert "<script>" not in body
    assert decode_overview(body) == current
    assert (
        body.index("**Next action:**")
        < body.index("<summary>Earlier Findings")
        < body.index("<summary>Review Details")
    )


def test_ten_realistic_concerns_fit_full_retention_and_do_not_truncate(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    findings = overview_envelope.complete_passes[0].artifact.findings
    archive = EarlierReviewFindings(
        concerns=tuple(
            EarlierReviewFinding(
                identity=f"concern-{index:02}",
                finding=findings[index % 3].model_copy(deep=True),
                pass_id="original-pass",
                head_sha="a" * 40,
                sequence=1,
                workflow_url="https://example.com/actions/runs/1",
            )
            for index in range(10)
        )
    )
    current = overview_envelope.model_copy(update={"earlier_findings": archive}, deep=True)
    for snapshot in current.complete_passes:
        snapshot.artifact.change_summary = ReviewChangeSummary(bullets=["\u6771" * 300] * 3)
    before = current.model_dump(mode="json")
    body = render_overview(current)
    assert len(body.encode("utf-8")) <= 60_000
    assert decode_overview(body) == current
    assert current.model_dump(mode="json") == before
    oversized = current.model_copy(deep=True)
    oversized.earlier_findings.concerns[0].finding.evidence = "\u6771" * 20_000
    with pytest.raises(ReviewOverviewError, match="payload budget"):
        render_overview(oversized)


def test_old_snapshots_are_adopted_even_after_metadata_serialization(
    overview_envelope: ReviewOverviewEnvelope,
) -> None:
    previous = _unlinked(overview_envelope)
    previous.complete_passes[0].artifact.findings.clear()
    previous.history[0] = previous.complete_passes[0].summary()
    # Metadata writes include newly defaulted fields even for historical envelopes.
    previous = ReviewOverviewEnvelope.model_validate_json(previous.model_dump_json())
    current = _next(
        previous, PublishableReviewArtifact(classification="no_findings", summary="Clear")
    )
    assert len(current.earlier_findings.concerns) == 3
    assert all(entry.sequence == 4 for entry in current.earlier_findings.concerns)
    assert current.earlier_findings.collected_through_sequence == 4
