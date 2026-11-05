"""Only request-bound cached evidence may restore presentation history."""

import pytest

from zeroone_ops.models.review_overview import EarlierReviewFindings, ReviewOverviewEnvelope
from zeroone_ops.models.state import ChangeRequestReviewState
from zeroone_ops.services.review.publish.review_overview_codec import ReviewOverviewAuthorityError
from zeroone_ops.services.review.publish.review_overview_recovery import recover_cached_overview
from zeroone_ops.utils.review_overview_identity import review_pass_identity


def _candidates(envelope: ReviewOverviewEnvelope) -> list[ChangeRequestReviewState]:
    """Use actual scope-bound receipts rather than synthetic historical pass labels."""
    result = []
    for snapshot in envelope.complete_passes:
        snapshot = snapshot.model_copy(
            deep=True,
            update={
                "pass_id": review_pass_identity(
                    platform=envelope.platform,
                    repository_id=envelope.repository_id,
                    change_request_number=envelope.change_request_number,
                    head_sha=snapshot.head_sha,
                    run_id=snapshot.run_id,
                )
            },
        )
        result.append(
            ChangeRequestReviewState(
                change_request_number=envelope.change_request_number,
                head_sha=snapshot.head_sha,
                status=snapshot.artifact.classification,
                last_run_id=snapshot.run_id,
                overview_pass=snapshot,
                earlier_findings=EarlierReviewFindings(evicted_count=3),
            )
        )
    return result


@pytest.mark.parametrize("mismatch", [None, "repository", "platform", "request", "head", "receipt"])
def test_recovery_verifies_scope_and_preserves_bounded_cache(overview_envelope, mismatch):
    candidates = _candidates(overview_envelope)
    repository_id = overview_envelope.repository_id
    platform = overview_envelope.platform
    number = overview_envelope.change_request_number
    if mismatch == "repository":
        repository_id = "other/repository"
    elif mismatch == "platform":
        platform = "gitlab"
    elif mismatch == "request":
        number += 1
    elif mismatch == "head":
        for cached in candidates:
            cached.head_sha = "different"
    elif mismatch == "receipt":
        for cached in candidates:
            cached.overview_pass = cached.overview_pass.model_copy(update={"pass_id": "foreign"})
    before = [cached.model_dump(mode="json") for cached in candidates]
    recovered = recover_cached_overview(
        platform=platform,
        repository_id=repository_id,
        change_request_number=number,
        candidates=candidates,
    )
    if mismatch is None:
        assert recovered.complete_passes == [cached.overview_pass for cached in candidates]
        assert recovered.earlier_findings.evicted_count == 3
        assert recovered.earlier_findings.history_unavailable
    else:
        assert recovered is None
    assert [cached.model_dump(mode="json") for cached in candidates] == before


def test_recovery_rejects_conflicting_sequence_authority(overview_envelope):
    candidates = _candidates(overview_envelope)
    conflict = candidates[0].model_copy(deep=True)
    conflict.earlier_findings = EarlierReviewFindings(evicted_count=99)
    with pytest.raises(ReviewOverviewAuthorityError, match="ambiguous"):
        recover_cached_overview(
            platform=overview_envelope.platform,
            repository_id=overview_envelope.repository_id,
            change_request_number=overview_envelope.change_request_number,
            candidates=[*candidates, conflict],
        )
