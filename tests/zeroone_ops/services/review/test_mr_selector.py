from __future__ import annotations

from zeroone_ops.models.review import MergeRequestReviewCandidate
from zeroone_ops.models.state import AppState, MergeRequestReviewState, RepositoryState
from zeroone_ops.services.review.mr_selector import (
    MergeRequestSelector,
    build_review_revision_key,
)


def build_merge_request(iid: int, head_sha: str) -> MergeRequestReviewCandidate:
    return MergeRequestReviewCandidate(
        iid=iid,
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
    state.reviews[build_review_revision_key(mr_iid=17, head_sha="abc123")] = (
        MergeRequestReviewState(
            mr_iid=17,
            head_sha="abc123",
            status="findings_present",
            last_run_id="run-1",
        )
    )

    selected = MergeRequestSelector().select(
        [build_merge_request(17, "abc123"), build_merge_request(18, "def456")],
        state,
    )

    assert selected is not None
    assert selected.iid == 18


def test_skip_reason_returns_already_reviewed_revision() -> None:
    state = build_state()
    state.reviews[build_review_revision_key(mr_iid=17, head_sha="abc123")] = (
        MergeRequestReviewState(
            mr_iid=17,
            head_sha="abc123",
            status="findings_present",
            last_run_id="run-1",
        )
    )

    reason = MergeRequestSelector().skip_reason(build_merge_request(17, "abc123"), state)

    assert reason == "already_reviewed_revision"


def test_skip_reason_reuses_manual_review_only_state() -> None:
    state = build_state()
    state.reviews[build_review_revision_key(mr_iid=17, head_sha="abc123")] = (
        MergeRequestReviewState(
            mr_iid=17,
            head_sha="abc123",
            status="manual_review_only",
            last_run_id="run-1",
        )
    )

    reason = MergeRequestSelector().skip_reason(build_merge_request(17, "abc123"), state)

    assert reason == "already_reviewed_revision"
