"""Shared policy-state reconciliation decisions for normalized findings."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.work_item import WorkItemState


@dataclass(frozen=True)
class PolicyReconciliationDecision:
    """Describe the safe policy-owned transition for one work item."""

    action: str
    reason: str | None = None


class FindingPolicyReconciliationService:
    """Keep policy deferral rules independent from provider issue transport."""

    def decide_for_current_finding(
        self,
        *,
        work_item: WorkItemState | None,
        policy_eligible: bool,
        promotion_eligible: bool,
    ) -> PolicyReconciliationDecision:
        """Return the policy transition for one finding still in inventory."""
        if work_item is None:
            return PolicyReconciliationDecision("none")
        if work_item.status == "policy_deferred":
            if not policy_eligible:
                return PolicyReconciliationDecision("retain_deferred")
            return PolicyReconciliationDecision(
                "reopen_approved" if promotion_eligible else "reopen_candidate"
            )
        if not policy_eligible:
            if (
                work_item.status in {"candidate", "approved"}
                and work_item.linked_change_request is None
            ):
                return PolicyReconciliationDecision("defer", "policy_ineligible")
            return PolicyReconciliationDecision("retain_protected")
        return PolicyReconciliationDecision("none")

    def decide_for_missing_finding(
        self,
        *,
        work_item: WorkItemState,
        source_is_managed: bool,
    ) -> PolicyReconciliationDecision:
        """Resolve deferred work only from a complete managed source inventory."""
        if work_item.status == "policy_deferred" and source_is_managed:
            return PolicyReconciliationDecision("complete_no_longer_detected")
        return PolicyReconciliationDecision("none")
