"""Shared default workflow policy for normalized findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.policy import PolicyState

FindingWorkflowDisposition = Literal["queue_candidate"]
FindingWorkflowReason = Literal["default_queue_candidate"]
FindingPromotionDisposition = Literal["promote", "backlog_only"]
FindingPromotionReason = Literal[
    "severity_enabled",
    "severity_disabled",
    "issue_class_excluded",
]


@dataclass(frozen=True)
class FindingWorkflowDecision:
    """Describe the shared default workflow decision for one finding."""

    disposition: FindingWorkflowDisposition
    reason: FindingWorkflowReason


@dataclass(frozen=True)
class FindingPromotionDecision:
    """Describe whether one normalized finding needs durable coordination."""

    disposition: FindingPromotionDisposition
    reason: FindingPromotionReason


class FindingWorkflowPolicyService:
    """Apply the first shared queueing rule for normalized findings."""

    def decide(self, *, finding: NormalizedFinding) -> FindingWorkflowDecision:
        """Return the shared default workflow decision for one normalized finding."""
        _ = finding
        return FindingWorkflowDecision(
            disposition="queue_candidate",
            reason="default_queue_candidate",
        )

    def decide_promotion(
        self,
        *,
        finding: NormalizedFinding,
        policy_state: PolicyState,
    ) -> FindingPromotionDecision:
        """Apply the shared policy state when deciding durable finding visibility."""
        enabled_severities = {
            entry.severity for entry in policy_state.severity_policy if entry.enabled
        }
        if finding.severity not in enabled_severities:
            return FindingPromotionDecision(
                disposition="backlog_only",
                reason="severity_disabled",
            )
        diagnostic_code = finding.remediation_context.diagnostic_code
        if diagnostic_code is not None and any(
            exclusion.source == finding.source_id and exclusion.issue_key == diagnostic_code
            for exclusion in policy_state.issue_class_exclusions
        ):
            return FindingPromotionDecision(
                disposition="backlog_only",
                reason="issue_class_excluded",
            )
        return FindingPromotionDecision(
            disposition="promote",
            reason="severity_enabled",
        )
