"""Verify request identity and failure evidence without checking out or mutating work."""

from unittest.mock import Mock

import pytest

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.remediation.revision_target_preparation_service import (
    RevisionTargetPreparationService,
)


@pytest.mark.parametrize(
    "mode",
    [
        "valid",
        "ordinary",
        "no_link",
        "no_review",
        "no_feedback",
        "no_lookup",
        "lookup_error",
        "wrong_number",
        "wrong_url",
        "closed",
        "head_drift",
        "refspec",
        "option",
        "space",
    ],
)
def test_revision_preparation_preserves_identity_guards_and_inputs(mode):
    feedback = ProjectedReviewFeedback(
        summary="Review",
        finding_count=1,
        findings=[
            ProjectedReviewFinding(
                title="Fix",
                file_path="src/app.py",
                evidence="Evidence",
                explanation="Impact",
                suggested_follow_up="Fix",
            )
        ],
    )
    link = ChangeRequestRef(number=9, web_url="https://example/pr/9")
    review = ProjectedReviewState(
        classification="findings_present",
        reviewed_sha="sha",
        follow_up_required=True,
        feedback=None if mode == "no_feedback" else feedback,
    )
    state = WorkItemState(
        work_item_id="work",
        kind="remediation",
        status="approved" if mode == "ordinary" else "review_revision_queued",
        summary="Fix",
        source=WorkItemSourceRef(
            source="ruff", source_item_key="finding", repository_scope="org/repo"
        ),
        linked_change_request=None if mode == "no_link" else link,
        projected_review=None if mode == "no_review" else review,
    )
    target = RemediationExecutionTarget(
        item_id="work",
        source_type="ruff",
        source_ref="finding",
        status=state.status,
        title="Fix",
        message="Fix",
        file_path="src/app.py",
    )
    lookup = Mock(
        return_value=ChangeRequestState(
            iid=8 if mode == "wrong_number" else 9,
            web_url="https://other/pr/9" if mode == "wrong_url" else link.web_url,
            state="closed" if mode == "closed" else "opened",
            head_sha="other" if mode == "head_drift" else "sha",
            source_branch={
                "refspec": "+refs/heads/a:refs/heads/b",
                "option": "--all",
                "space": "bad branch",
            }.get(mode, "remediation"),
        )
    )
    if mode == "lookup_error":
        lookup.side_effect = RuntimeError("Unavailable")
    service = RevisionTargetPreparationService(
        change_request_state_lookup=None if mode == "no_lookup" else lookup
    )
    lookup.assert_not_called()
    before = state.model_dump_json(), target.model_dump_json()

    prepared, failure = service.prepare(selected_target=target, claimed_work_item=state)

    assert before == (state.model_dump_json(), target.model_dump_json())
    if mode == "valid":
        assert failure is None
        assert prepared.review_feedback == feedback
        assert prepared.revision_branch == "remediation" and prepared.reviewed_sha == "sha"
        assert prepared.revision_change_request == link
    elif mode == "ordinary":
        assert failure is None and prepared is target
    else:
        assert prepared is target and failure.stage.value == "issue_intake"
    if mode in {"ordinary", "no_link", "no_review", "no_feedback", "no_lookup"}:
        lookup.assert_not_called()
    else:
        lookup.assert_called_once_with(9)
