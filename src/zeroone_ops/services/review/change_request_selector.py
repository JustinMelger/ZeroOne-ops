"""Change-request selection rules."""

from __future__ import annotations

from zeroone_ops.models.review import ChangeRequestReviewCandidate
from zeroone_ops.models.state import AppState, ChangeRequestReviewState

_AUTHORITATIVE_REVIEW_STATUSES = frozenset(
    {"no_findings", "findings_present", "manual_review_only"}
)


def build_review_revision_key(*, change_request_number: int, head_sha: str) -> str:
    """Build the stable dedup key for one change-request revision."""
    return f"{change_request_number}:{head_sha}"


class ChangeRequestSelector:
    """Select one reviewable change request for a run."""

    def select(
        self,
        change_requests: list[ChangeRequestReviewCandidate],
        state: AppState,
    ) -> ChangeRequestReviewCandidate | None:
        """Select the next change request to review."""
        for change_request in change_requests:
            if self.skip_reason(change_request, state) is not None:
                continue
            return change_request
        return None

    def skip_reason(
        self,
        change_request: ChangeRequestReviewCandidate,
        state: AppState,
    ) -> str | None:
        """Return why a change request should be skipped."""
        dedup_key = build_review_revision_key(
            change_request_number=change_request.change_request_number,
            head_sha=change_request.head_sha,
        )
        review_state = state.reviews.get(dedup_key)
        if review_state is not None and _is_successful_review_state(review_state):
            return "already_reviewed_revision"
        return None


def _is_successful_review_state(review_state: ChangeRequestReviewState) -> bool:
    """Return whether one persisted review state is authoritative for same-SHA reuse."""
    return review_state.status in _AUTHORITATIVE_REVIEW_STATUSES
