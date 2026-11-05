"""Recover bounded presentation history from verifiably request-scoped local evidence."""

from typing import Literal

from zeroone_ops.models.review_overview import (
    EarlierReviewFindings,
    ReviewOverviewEnvelope,
    ReviewOverviewPass,
)
from zeroone_ops.models.state import ChangeRequestReviewState
from zeroone_ops.services.review.publish.review_overview_codec import ReviewOverviewAuthorityError
from zeroone_ops.utils.review_overview_identity import review_pass_identity


def recover_cached_overview(
    *,
    platform: Literal["github", "gitlab"],
    repository_id: str,
    change_request_number: int,
    candidates: list[ChangeRequestReviewState],
) -> ReviewOverviewEnvelope | None:
    """Return bounded verified history, never treating a cached pass as a new-head review."""
    verified: dict[int, tuple[ReviewOverviewPass, EarlierReviewFindings]] = {}
    for cached in candidates:
        snapshot = cached.overview_pass
        if (
            snapshot is None
            or cached.change_request_number != change_request_number
            or cached.head_sha != snapshot.head_sha
            or snapshot.pass_id
            != review_pass_identity(
                platform=platform,
                repository_id=repository_id,
                change_request_number=change_request_number,
                head_sha=snapshot.head_sha,
                run_id=snapshot.run_id,
            )
        ):
            continue
        existing = verified.get(snapshot.sequence)
        entry = (snapshot, cached.earlier_findings)
        if existing is not None and existing != entry:
            raise ReviewOverviewAuthorityError("Cached review history is ambiguous.")
        verified[snapshot.sequence] = entry
    ordered = [verified[sequence] for sequence in sorted(verified, reverse=True)]
    if not ordered:
        return None

    snapshots = [snapshot.model_copy(deep=True) for snapshot, _ in ordered[:5]]
    archive = ordered[0][1].model_copy(deep=True)
    if snapshots[0].sequence > len(snapshots):
        archive = archive.model_copy(update={"history_unavailable": True})
    return ReviewOverviewEnvelope(
        platform=platform,
        repository_id=repository_id,
        change_request_number=change_request_number,
        complete_passes=snapshots[:2],
        history=[snapshot.summary() for snapshot in snapshots],
        earlier_findings=archive,
    )
