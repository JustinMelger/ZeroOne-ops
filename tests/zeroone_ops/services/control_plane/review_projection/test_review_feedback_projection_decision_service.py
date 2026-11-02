from datetime import UTC, datetime, timedelta

import pytest

from zeroone_ops.models.review import PublishableReviewArtifact
from zeroone_ops.models.work_item import (
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    ReviewRevisionRequest,
    WorkItemClaim,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.control_plane.review_projection.review_feedback_projection_decision_service import (  # noqa: E501
    ReviewFeedbackProjectionDecisionService,
)

NOW = datetime(2026, 11, 2, tzinfo=UTC)
URL = "https://example.com/review#note-2"


def _work_item() -> WorkItemState:
    revision = ReviewRevisionRequest(
        actor="operator",
        request_reference="issue-comment-1",
        occurred_at=NOW,
        reviewed_sha="abc123",
    )
    return WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="review_revision_queued",
        source=WorkItemSourceRef(source="sonarqube", source_item_key="AX123"),
        summary="Fix error handling.",
        projected_review=ProjectedReviewState(
            classification="findings_present",
            reviewed_sha="abc123",
            review_note_reference="review-pass-1",
            follow_up_required=True,
            feedback=ProjectedReviewFeedback(
                summary="The error path still needs correction.",
                finding_count=1,
                findings=[
                    ProjectedReviewFinding(
                        title="Preserve the error response.",
                        file_path="src/api.py",
                        evidence="The branch returns success on failure.",
                        explanation="Errors are hidden.",
                        suggested_follow_up="Return the error response.",
                    )
                ],
            ),
        ),
        review_revision_request=revision,
        last_revision_command=revision,
        review_action_required_at=NOW,
        claim=WorkItemClaim(claimed_at=NOW, run_id="run-1"),
    )


@pytest.mark.parametrize("status", ["review_feedback_required", "review_revision_queued"])
@pytest.mark.parametrize("action_timestamp", [None, NOW])
@pytest.mark.parametrize("old_url", [None, "https://example.com/review#note-1"])
def test_same_receipt_url_repair_preserves_all_other_state(
    status: str, action_timestamp: datetime | None, old_url: str | None
) -> None:
    work_item = _work_item()
    assert work_item.projected_review is not None
    work_item = work_item.model_copy(
        update={
            "status": status,
            "review_action_required_at": action_timestamp,
            "projected_review": work_item.projected_review.model_copy(
                update={"review_note_url": old_url}
            ),
        }
    )

    def unexpected_clock() -> datetime:
        pytest.fail("Transport repair must not consult the action clock.")

    result = ReviewFeedbackProjectionDecisionService(clock=unexpected_clock).decide(
        work_item=work_item,
        artifact=PublishableReviewArtifact(classification="no_findings", summary="Changed input."),
        reviewed_sha="abc123",
        review_note_url=URL,
        review_note_reference="review-pass-1",
    )

    assert result.action == "updated"
    assert result.warning is None
    assert work_item.projected_review is not None
    assert result.work_item == work_item.model_copy(
        update={
            "projected_review": work_item.projected_review.model_copy(
                update={"review_note_url": URL}
            )
        }
    )


@pytest.mark.parametrize("incoming_url", [None, URL])
def test_same_receipt_without_url_repair_preserves_legacy_timestamp_backfill(
    incoming_url: str | None,
) -> None:
    work_item = _work_item()
    assert work_item.projected_review is not None
    work_item = work_item.model_copy(
        update={
            "status": "review_feedback_required",
            "review_action_required_at": None,
            "projected_review": work_item.projected_review.model_copy(
                update={"review_note_url": URL}
            ),
        }
    )

    result = ReviewFeedbackProjectionDecisionService(clock=lambda: NOW).decide(
        work_item=work_item,
        artifact=PublishableReviewArtifact(classification="no_findings", summary="Changed input."),
        reviewed_sha="abc123",
        review_note_url=incoming_url,
        review_note_reference="review-pass-1",
    )

    assert result.action == "updated"
    assert result.work_item == work_item.model_copy(update={"review_action_required_at": NOW})


@pytest.mark.parametrize("incoming_url", [None, URL])
def test_same_receipt_without_url_repair_is_unchanged(incoming_url: str | None) -> None:
    work_item = _work_item()
    assert work_item.projected_review is not None
    work_item = work_item.model_copy(
        update={
            "projected_review": work_item.projected_review.model_copy(
                update={"review_note_url": URL}
            )
        }
    )

    result = ReviewFeedbackProjectionDecisionService().decide(
        work_item=work_item,
        artifact=PublishableReviewArtifact(classification="no_findings", summary="Changed input."),
        reviewed_sha="abc123",
        review_note_url=incoming_url,
        review_note_reference="review-pass-1",
    )

    assert result.action == "unchanged"
    assert result.work_item == work_item


@pytest.mark.parametrize(
    ("reviewed_sha", "receipt"), [("abc123", "review-pass-2"), ("def456", "review-pass-1")]
)
def test_different_sha_or_receipt_keeps_legacy_transition(reviewed_sha: str, receipt: str) -> None:
    work_item = _work_item()
    result = ReviewFeedbackProjectionDecisionService(clock=lambda: NOW + timedelta(days=1)).decide(
        work_item=work_item,
        artifact=PublishableReviewArtifact(classification="no_findings", summary="Resolved."),
        reviewed_sha=reviewed_sha,
        review_note_url=URL,
        review_note_reference=receipt,
    )

    assert result.action == "updated"
    assert result.work_item.status == "in_progress"
    assert result.work_item.claim is None
    assert result.work_item.review_revision_request is None
    assert result.work_item.last_revision_command == work_item.last_revision_command
    assert result.work_item.review_action_required_at == NOW
    assert result.work_item.projected_review is not None
    assert result.work_item.projected_review.classification == "no_findings"
    assert result.work_item.projected_review.reviewed_sha == reviewed_sha
    assert result.work_item.projected_review.review_note_reference == receipt
