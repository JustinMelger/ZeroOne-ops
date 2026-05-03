"""Merge request selection rules."""

from __future__ import annotations

from zeroone_ops.models.review import MergeRequestReviewCandidate
from zeroone_ops.models.state import AppState, MergeRequestReviewState

_AUTHORITATIVE_REVIEW_STATUSES = frozenset(
    {"no_findings", "findings_present", "manual_review_only"}
)


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
        review_state = state.reviews.get(dedup_key)
        if review_state is not None and _is_successful_review_state(review_state):
            return "already_reviewed_revision"
        return None


def _is_successful_review_state(review_state: MergeRequestReviewState) -> bool:
    """Return whether one persisted review state is authoritative for same-SHA reuse."""
    return review_state.status in _AUTHORITATIVE_REVIEW_STATUSES
