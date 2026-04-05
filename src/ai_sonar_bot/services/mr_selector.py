"""Merge request selection rules."""

from __future__ import annotations

from ai_sonar_bot.models.review import MergeRequestReviewCandidate
from ai_sonar_bot.models.state import AppState


def build_review_revision_key(*, mr_iid: int, head_sha: str) -> str:
    """Build the stable dedup key for an MR revision."""
    return f"{mr_iid}:{head_sha}"


class MergeRequestSelector:
    """Select one reviewable merge request for a run."""

    def select(
        self,
        merge_requests: list[MergeRequestReviewCandidate],
        state: AppState,
    ) -> MergeRequestReviewCandidate | None:
        """Select the next merge request to review."""
        for merge_request in merge_requests:
            if self.skip_reason(merge_request, state) is not None:
                continue
            return merge_request
        return None

    def skip_reason(
        self,
        merge_request: MergeRequestReviewCandidate,
        state: AppState,
    ) -> str | None:
        """Return why a merge request should be skipped."""
        dedup_key = build_review_revision_key(
            mr_iid=merge_request.iid,
            head_sha=merge_request.head_sha,
        )
        if dedup_key in state.reviews:
            return "already_reviewed_revision"
        return None
