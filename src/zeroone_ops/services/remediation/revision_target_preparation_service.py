"""Verify a queued revision target without checkout, execution, or state writes."""

from __future__ import annotations

from collections.abc import Callable

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import FailureDetails, FailureStage
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.remediation.batch_execution_scope_service import (
    BatchExecutionScopeService,
)
from zeroone_ops.utils.git import is_literal_branch_argument


class RevisionTargetPreparationService:
    """Verify existing linked-request identity and retain the recorded revision scope."""

    def __init__(
        self,
        *,
        change_request_state_lookup: Callable[[int], ChangeRequestState] | None,
    ) -> None:
        """Retain optional provider lookup without performing access."""
        self.change_request_state_lookup = change_request_state_lookup

    def prepare(
        self,
        *,
        selected_target: RemediationExecutionTarget,
        claimed_work_item: WorkItemState,
    ) -> tuple[RemediationExecutionTarget, FailureDetails | None]:
        """Verify a queued revision still targets the reviewed open change request."""
        if claimed_work_item.status != "review_revision_queued":
            return selected_target, None
        if claimed_work_item.batch is not None:
            scope = BatchExecutionScopeService().resolve(claimed_work_item, None)
            if scope.disposition != "execute":
                return selected_target, FailureDetails(
                    stage=FailureStage.ISSUE_INTAKE,
                    message=scope.reason or "Recorded batch revision scope is missing.",
                )
        linked = claimed_work_item.linked_change_request
        projected = claimed_work_item.projected_review
        if linked is None or projected is None or projected.feedback is None:
            return selected_target, FailureDetails(
                stage=FailureStage.ISSUE_INTAKE,
                message="Queued review revision is missing linked change-request feedback.",
            )
        if self.change_request_state_lookup is None:
            return selected_target, FailureDetails(
                stage=FailureStage.ISSUE_INTAKE,
                message="Queued review revision cannot load the linked change request.",
            )
        try:
            state = self.change_request_state_lookup(linked.number)
        except Exception as error:
            return selected_target, FailureDetails(
                stage=FailureStage.ISSUE_INTAKE,
                message=(
                    f"Queued review revision could not verify the linked change request: {error}"
                ),
            )
        if (
            state.iid != linked.number
            or state.web_url != linked.web_url
            or state.state != "opened"
            or state.head_sha != projected.reviewed_sha
            or not is_literal_branch_argument(state.source_branch)
        ):
            return selected_target, FailureDetails(
                stage=FailureStage.ISSUE_INTAKE,
                message=(
                    "Queued review revision is stale; request a current review before requeueing."
                ),
            )
        return selected_target.model_copy(
            update={
                "review_feedback": projected.feedback,
                "revision_branch": state.source_branch,
                "reviewed_sha": projected.reviewed_sha,
                "revision_change_request": linked,
            }
        ), None
