"""Route authorized work-item commands through provider-neutral decisions."""

from __future__ import annotations

from datetime import datetime

from zeroone_ops.models.work_item import RecoveryAction, WorkItemState
from zeroone_ops.services.remediation.recovery.recovery_decision_service import (
    RecoveryDecision,
    RecoveryDecisionService,
    RecoveryRequest,
)
from zeroone_ops.services.remediation.recovery.review_feedback_decision_service import (
    ReviewFeedbackDecision,
    ReviewFeedbackDecisionService,
    ReviewFeedbackRequest,
)

WorkItemCommandDecision = RecoveryDecision | ReviewFeedbackDecision


class WorkItemCommandDecisionService:
    """Route state-aware recovery and feedback commands without provider transport."""

    def __init__(
        self,
        *,
        recovery_decision_service: RecoveryDecisionService,
        review_feedback_decision_service: ReviewFeedbackDecisionService,
    ) -> None:
        """Initialize the shared command router."""
        self.recovery_decision_service = recovery_decision_service
        self.review_feedback_decision_service = review_feedback_decision_service

    def decide(
        self,
        *,
        work_item: WorkItemState,
        action: RecoveryAction,
        actor: str,
        request_reference: str,
        occurred_at: datetime,
        policy_eligible: bool,
    ) -> WorkItemCommandDecision:
        """Route one authorized command from the authoritative work-item state."""
        fingerprint = self.recovery_decision_service.state_fingerprint(work_item)
        if action == "requeue" and work_item.status == "review_feedback_required":
            return self.review_feedback_decision_service.decide(
                work_item=work_item,
                request=ReviewFeedbackRequest(
                    actor=actor,
                    request_reference=request_reference,
                    expected_state_fingerprint=fingerprint,
                    occurred_at=occurred_at,
                ),
            )
        return self.recovery_decision_service.decide(
            work_item=work_item,
            request=RecoveryRequest(
                action=action,
                actor=actor,
                request_reference=request_reference,
                expected_state_fingerprint=fingerprint,
                occurred_at=occurred_at,
            ),
            policy_eligible=policy_eligible,
        )
