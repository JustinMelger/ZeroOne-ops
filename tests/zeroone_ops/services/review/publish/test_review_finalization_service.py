from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from zeroone_ops.models.review import ChangeRequestReviewCandidate, ReviewComment
from zeroone_ops.services.review.publish.review_finalization_service import (
    ReviewFinalizationService,
)
from zeroone_ops.services.review.publish.review_publisher import ReviewPublishResult

from .support import build_artifact, build_context


@dataclass
class FakeReviewPublisher:
    result: ReviewPublishResult

    def publish_artifact(self, **_: object) -> ReviewPublishResult:
        return self.result


class FakeReviewProjectionService:
    def __init__(self, *, action: str = "updated", error: Exception | None = None) -> None:
        self.action = action
        self.error = error
        self.calls: list[dict[str, object]] = []

    def project_review(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(action=self.action)


def test_finalize_projects_review_after_successful_publish() -> None:
    context = build_context()
    projection_service = FakeReviewProjectionService(action="updated")
    finalization = ReviewFinalizationService(
        review_publisher=FakeReviewPublisher(
            ReviewPublishResult(
                note=ReviewComment(id=42, web_url="https://example.com/note/42"),
                body="body",
                artifact=build_artifact(),
            )
        ),
        dashboard_updater=None,
        review_projection_factory=lambda: projection_service,
    )

    result = finalization.finalize(
        run_id="run-1",
        repository_id="owner/repo",
        active_dry_run=False,
        change_request=_build_change_request_candidate(),
        context=context,
        artifact=build_artifact(),
        inline_comment_decisions=[],
    )

    assert result.error_message is None
    assert result.projection_warning is None
    assert len(projection_service.calls) == 1
    assert projection_service.calls[0] == {
        "repository_id": "owner/repo",
        "context": context,
        "classification": "findings_present",
        "reviewed_sha": "abc123",
        "review_note_url": "https://example.com/note/42",
    }


def test_finalize_ignores_no_matching_work_item_projection() -> None:
    finalization = ReviewFinalizationService(
        review_publisher=FakeReviewPublisher(
            ReviewPublishResult(
                note=ReviewComment(id=42, web_url="https://example.com/note/42"),
                body="body",
                artifact=build_artifact(),
            )
        ),
        dashboard_updater=None,
        review_projection_factory=lambda: FakeReviewProjectionService(
            action="no_matching_work_item"
        ),
    )

    result = finalization.finalize(
        run_id="run-1",
        repository_id="owner/repo",
        active_dry_run=False,
        change_request=_build_change_request_candidate(),
        context=build_context(),
        artifact=build_artifact(),
        inline_comment_decisions=[],
    )

    assert result.error_message is None
    assert result.projection_warning is None


def test_finalize_downgrades_projection_failures_to_warning() -> None:
    finalization = ReviewFinalizationService(
        review_publisher=FakeReviewPublisher(
            ReviewPublishResult(
                note=ReviewComment(id=42, web_url="https://example.com/note/42"),
                body="body",
                artifact=build_artifact(),
            )
        ),
        dashboard_updater=None,
        review_projection_factory=lambda: FakeReviewProjectionService(
            error=RuntimeError("projection boom")
        ),
    )

    result = finalization.finalize(
        run_id="run-1",
        repository_id="owner/repo",
        active_dry_run=False,
        change_request=_build_change_request_candidate(),
        context=build_context(),
        artifact=build_artifact(),
        inline_comment_decisions=[],
    )

    assert result.error_message is None
    assert result.projection_warning == "Review projection warning: projection boom"


def test_finalize_skips_projection_during_dry_run() -> None:
    projection_service = FakeReviewProjectionService(action="updated")
    finalization = ReviewFinalizationService(
        review_publisher=FakeReviewPublisher(
            ReviewPublishResult(
                note=ReviewComment(id=42, web_url="https://example.com/note/42"),
                body="body",
                artifact=build_artifact(),
            )
        ),
        dashboard_updater=None,
        review_projection_factory=lambda: projection_service,
    )

    result = finalization.finalize(
        run_id="run-1",
        repository_id="owner/repo",
        active_dry_run=True,
        change_request=_build_change_request_candidate(),
        context=build_context(),
        artifact=build_artifact(),
        inline_comment_decisions=[],
    )

    assert result.error_message is None
    assert result.projection_warning is None
    assert projection_service.calls == []


def _build_change_request_candidate() -> ChangeRequestReviewCandidate:
    return ChangeRequestReviewCandidate(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
    )
