"""Apply provider-neutral operator recovery decisions to remediation work items."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from zeroone_ops.models.work_item import RecoveryAction, RecoveryEvent, RecoveryPlan, WorkItemState

_MAX_RECOVERY_EVENTS = 10


@dataclass(frozen=True)
class RecoveryRequest:
    """Represent one provider-authorized operator request against known item state."""

    action: RecoveryAction
    actor: str
    request_reference: str
    expected_state_fingerprint: str
    occurred_at: datetime
    reason: str | None = None


@dataclass(frozen=True)
class RecoveryDecision:
    """Return the accepted state transition or a stable rejection explanation."""

    accepted: bool
    message: str
    work_item: WorkItemState
    plan: RecoveryPlan | None = None


class RecoveryDecisionService:
    """Decide bounded recovery transitions without provider or transport dependencies."""

    def decide(
        self,
        *,
        work_item: WorkItemState,
        request: RecoveryRequest,
        policy_eligible: bool,
    ) -> RecoveryDecision:
        """Validate and apply one recovery request to a blocked remediation item."""
        if work_item.kind != "remediation":
            return self._reject(work_item, "Recovery is available only for remediation work items.")
        if work_item.status != "blocked":
            return self._reject(
                work_item,
                "Recovery is available only while the work item is blocked.",
            )
        if request.expected_state_fingerprint != self.state_fingerprint(work_item):
            return self._reject(
                work_item,
                "Recovery request is stale because the authoritative work item changed.",
            )
        if request.action not in {"dismiss", "requeue"}:
            return self._reject(work_item, "Unsupported remediation recovery action.")
        if request.action == "dismiss":
            return self._accept(
                work_item=work_item,
                request=request,
                status="dismissed",
                plan=None,
                message="Remediation was dismissed by the operator.",
            )
        if self._can_retry_publication(work_item):
            return self._accept(
                work_item=work_item,
                request=request,
                status="approved",
                plan="retry_publication",
                message="Recorded branch publication was queued for verification.",
            )
        if not policy_eligible:
            return self._reject(
                work_item,
                "Recovery cannot start a fresh attempt because current policy does not allow it.",
            )
        return self._accept(
            work_item=work_item,
            request=request,
            status="approved",
            plan="start_fresh",
            message="A fresh remediation attempt was queued.",
        )

    @staticmethod
    def state_fingerprint(work_item: WorkItemState) -> str:
        """Return a stable fingerprint used to reject stale recovery commands."""
        payload = work_item.model_dump(mode="json", exclude_none=True)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _accept(
        self,
        *,
        work_item: WorkItemState,
        request: RecoveryRequest,
        status: Literal["approved", "dismissed"],
        plan: RecoveryPlan | None,
        message: str,
    ) -> RecoveryDecision:
        attempt_number = work_item.attempt_number + (1 if plan == "start_fresh" else 0)
        event = RecoveryEvent(
            action=request.action,
            actor=request.actor,
            request_reference=request.request_reference,
            occurred_at=request.occurred_at,
            previous_status=work_item.status,
            resulting_status=status,
            previous_attempt_number=work_item.attempt_number,
            resulting_attempt_number=attempt_number,
            plan=plan,
            reason=request.reason,
            prior_change_request=work_item.linked_change_request,
            prior_publication_retry=work_item.publication_retry,
            prior_execution_failure=work_item.execution_failure,
        )
        update: dict[str, object] = {
            "status": status,
            "attempt_number": attempt_number,
            "recovery_events": [*work_item.recovery_events, event][-_MAX_RECOVERY_EVENTS:],
        }
        if plan == "start_fresh":
            update.update(
                {
                    "claim": None,
                    "linked_change_request": None,
                    "projected_review": None,
                    "publication_retry": None,
                    "execution_failure": None,
                    "resolution": None,
                }
            )
        return RecoveryDecision(
            accepted=True,
            message=message,
            work_item=work_item.model_copy(update=update),
            plan=plan,
        )

    @staticmethod
    def _can_retry_publication(work_item: WorkItemState) -> bool:
        """Return whether the item records the narrow safe publication-retry state."""
        return work_item.publication_retry is not None and work_item.linked_change_request is None

    @staticmethod
    def _reject(work_item: WorkItemState, message: str) -> RecoveryDecision:
        """Return one unchanged rejected decision."""
        return RecoveryDecision(
            accepted=False,
            message=message,
            work_item=work_item,
        )
