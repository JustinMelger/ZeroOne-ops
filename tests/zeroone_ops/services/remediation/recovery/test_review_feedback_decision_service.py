"""Test provider-neutral remediation review-feedback decisions."""

from datetime import UTC, datetime, timedelta

import pytest

from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.remediation.recovery.recovery_decision_service import (
    RecoveryDecisionService,
)
from zeroone_ops.services.remediation.recovery.review_feedback_decision_service import (
    ReviewFeedbackDecisionService,
    ReviewFeedbackRequest,
)
from zeroone_ops.services.remediation.recovery.work_item_command_decision_service import (
    WorkItemCommandDecisionService,
)


def _work_item() -> WorkItemState:
    return WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="review_feedback_required",
        review_action_required_at=datetime(2026, 9, 14, tzinfo=UTC),
        source=WorkItemSourceRef(source="ruff-sarif", source_item_key="F401:src/api.py:42"),
        summary="Unused import.",
        file_path="src/api.py",
        linked_change_request=ChangeRequestRef(
            number=9,
            web_url="https://example.test/pull/9",
        ),
        projected_review=ProjectedReviewState(
            classification="findings_present",
            reviewed_sha="reviewed-sha",
            review_note_reference="github-comment-1",
            follow_up_required=True,
            feedback=ProjectedReviewFeedback(
                summary="Preserve the error path.",
                finding_count=1,
                findings=[
                    ProjectedReviewFinding(
                        title="Preserve errors.",
                        file_path="src/api.py",
                        line_start=42,
                        evidence="The changed branch returns success.",
                        explanation="Clients receive an incorrect response.",
                        suggested_follow_up="Retain the error response.",
                    )
                ],
            ),
        ),
    )


def test_feedback_requeue_queues_one_revision() -> None:
    work_item = _work_item()
    decision = ReviewFeedbackDecisionService().decide(
        work_item=work_item,
        request=ReviewFeedbackRequest(
            actor="operator",
            request_reference="github-comment-2",
            expected_state_fingerprint=RecoveryDecisionService.state_fingerprint(work_item),
            occurred_at=datetime(2026, 9, 15, tzinfo=UTC),
        ),
    )

    assert decision.accepted is True
    assert decision.work_item.status == "review_revision_queued"
    assert decision.work_item.review_revision_request is not None
    assert decision.work_item.review_revision_request.reviewed_sha == "reviewed-sha"
    assert decision.work_item.last_revision_command == decision.work_item.review_revision_request


@pytest.mark.parametrize("seconds, accepted", [(-1, False), (0, False), (1, True)])
def test_receipt_rejects_older_commands_but_allows_fresh_decisions(seconds, accepted):
    work_item = _work_item()
    service = ReviewFeedbackDecisionService()
    timestamp = datetime(2026, 9, 19, tzinfo=UTC)
    queued = service.decide(
        work_item=work_item,
        request=ReviewFeedbackRequest(
            actor="operator",
            request_reference="note-1",
            occurred_at=timestamp,
            expected_state_fingerprint=RecoveryDecisionService.state_fingerprint(work_item),
        ),
    ).work_item
    failed = queued.model_copy(
        update={
            "status": "review_feedback_required",
            "review_revision_request": None,
        }
    )
    decision = service.decide(
        work_item=failed,
        request=ReviewFeedbackRequest(
            actor="operator",
            request_reference="note-2",
            occurred_at=timestamp + timedelta(seconds=seconds),
            expected_state_fingerprint=RecoveryDecisionService.state_fingerprint(failed),
        ),
    )
    assert decision.accepted is accepted


def test_command_router_rejects_feedback_dismissal_without_recovery_transition() -> None:
    work_item = _work_item()
    router = WorkItemCommandDecisionService(
        recovery_decision_service=RecoveryDecisionService(),
        review_feedback_decision_service=ReviewFeedbackDecisionService(),
    )

    decision = router.decide(
        work_item=work_item,
        action="dismiss",
        actor="operator",
        request_reference="github-comment-2",
        occurred_at=datetime(2026, 9, 15, tzinfo=UTC),
        policy_eligible=True,
    )

    assert decision.accepted is False
    assert decision.work_item == work_item


@pytest.mark.parametrize("offset, accepted", [(-1, False), (0, False), (1, True)])
def test_requeue_must_follow_current_feedback_boundary(offset, accepted):
    work_item = _work_item()
    boundary = work_item.review_action_required_at
    assert boundary is not None
    decision = ReviewFeedbackDecisionService().decide(
        work_item=work_item,
        request=ReviewFeedbackRequest(
            actor="operator",
            request_reference="previously-rejected-command",
            occurred_at=boundary + timedelta(seconds=offset),
            expected_state_fingerprint=RecoveryDecisionService.state_fingerprint(work_item),
        ),
    )
    assert decision.accepted is accepted


@pytest.mark.parametrize("boundary", [None, datetime(2026, 9, 14)])
def test_unknown_feedback_boundary_fails_closed(boundary):
    work_item = _work_item().model_copy(update={"review_action_required_at": boundary})
    decision = ReviewFeedbackDecisionService().decide(
        work_item=work_item,
        request=ReviewFeedbackRequest(
            actor="operator",
            request_reference="note-1",
            occurred_at=datetime(2026, 9, 15, tzinfo=UTC),
            expected_state_fingerprint=RecoveryDecisionService.state_fingerprint(work_item),
        ),
    )
    assert not decision.accepted
    assert "boundary is unavailable" in decision.message
