from __future__ import annotations

from zeroone_ops.models.review import ChangeRequestReviewCandidate
from zeroone_ops.models.state import AppState, ChangeRequestReviewState, RepositoryState
from zeroone_ops.services.review.intake.change_request_selector import (
    ChangeRequestSelector,
    build_review_revision_key,
)


def build_merge_request(iid: int, head_sha: str) -> ChangeRequestReviewCandidate:
    return ChangeRequestReviewCandidate(
        change_request_number=iid,
        title=f"feat: review {iid}",
        description="summary",
        source_branch=f"feature/{iid}",
        target_branch="main",
        web_url=f"https://gitlab.example.com/group/project/-/merge_requests/{iid}",
        head_sha=head_sha,
    )


def build_state() -> AppState:
    return AppState(repository=RepositoryState(base_branch="main"))


def test_select_skips_already_reviewed_revision_and_moves_to_next() -> None:
    state = build_state()
    state.reviews[build_review_revision_key(change_request_number=17, head_sha="abc123")] = (
        ChangeRequestReviewState(
            change_request_number=17,
            head_sha="abc123",
            status="findings_present",
            last_run_id="run-1",
        )
    )

    selected = ChangeRequestSelector().select(
        [build_merge_request(17, "abc123"), build_merge_request(18, "def456")],
        state,
    )

    assert selected is not None
    assert selected.change_request_number == 18


def test_skip_reason_returns_already_reviewed_revision() -> None:
    state = build_state()
    state.reviews[build_review_revision_key(change_request_number=17, head_sha="abc123")] = (
        ChangeRequestReviewState(
            change_request_number=17,
            head_sha="abc123",
            status="findings_present",
            last_run_id="run-1",
        )
    )

    reason = ChangeRequestSelector().skip_reason(build_merge_request(17, "abc123"), state)

    assert reason == "already_reviewed_revision"


def test_skip_reason_reuses_manual_review_only_state() -> None:
    state = build_state()
    state.reviews[build_review_revision_key(change_request_number=17, head_sha="abc123")] = (
        ChangeRequestReviewState(
            change_request_number=17,
            head_sha="abc123",
            status="manual_review_only",
            last_run_id="run-1",
        )
    )

    reason = ChangeRequestSelector().skip_reason(build_merge_request(17, "abc123"), state)

    assert reason == "already_reviewed_revision"
