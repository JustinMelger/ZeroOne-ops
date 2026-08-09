"""Plan bounded durable promotion for normalized findings."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingPromotionDecision,
    FindingWorkflowPolicyService,
)

_ACTIVE_STATUSES = {"approved", "in_progress"}
_PROTECTED_STATUSES = {"blocked", "dismissed"}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class FindingPromotionCapacityPlan:
    """Describe promotion decisions after applying active-work capacity."""

    decisions: dict[tuple[str, str], FindingPromotionDecision]
    active_work_item_count: int

    def decision_for(self, finding: NormalizedFinding) -> FindingPromotionDecision:
        """Return the planned decision for one normalized finding."""
        return self.decisions[(finding.source_id, finding.finding_id)]


class FindingPromotionCapacityService:
    """Apply one shared active remediation capacity after policy evaluation."""

    def __init__(
        self,
        workflow_policy_service: FindingWorkflowPolicyService | None = None,
    ) -> None:
        """Initialize the shared policy dependency."""
        self.workflow_policy_service = workflow_policy_service or FindingWorkflowPolicyService()

    def plan(
        self,
        *,
        findings: list[NormalizedFinding],
        policy_state: PolicyState,
        open_work_items: list[WorkItemState],
        repository_scope: str,
        max_active_work_items: int,
    ) -> FindingPromotionCapacityPlan:
        """Return policy and capacity decisions for one complete finding inventory."""
        decisions = {
            (finding.source_id, finding.finding_id): self.workflow_policy_service.decide_promotion(
                finding=finding,
                policy_state=policy_state,
            )
            for finding in findings
        }
        active_keys = {
            (work_item.source.source, work_item.source.source_item_key)
            for work_item in open_work_items
            if work_item.kind == "remediation"
            and work_item.source.repository_scope == repository_scope
            and work_item.status in _ACTIVE_STATUSES
        }
        active_work_item_count = sum(
            1
            for work_item in open_work_items
            if work_item.kind == "remediation"
            and work_item.source.repository_scope == repository_scope
            and work_item.status in _ACTIVE_STATUSES
        )
        protected_keys = {
            (work_item.source.source, work_item.source.source_item_key)
            for work_item in open_work_items
            if work_item.kind == "remediation"
            and work_item.source.repository_scope == repository_scope
            and work_item.status in _PROTECTED_STATUSES
        }
        available_capacity = max(max_active_work_items - active_work_item_count, 0)
        candidate_findings = [
            finding
            for finding in findings
            if decisions[(finding.source_id, finding.finding_id)].disposition == "promote"
            and (finding.source_id, finding.finding_id) not in active_keys
            and (finding.source_id, finding.finding_id) not in protected_keys
        ]
        candidate_findings.sort(
            key=lambda finding: (
                _SEVERITY_ORDER[finding.severity],
                finding.source_id,
                finding.finding_id,
            )
        )
        for finding in candidate_findings[available_capacity:]:
            decisions[(finding.source_id, finding.finding_id)] = FindingPromotionDecision(
                disposition="backlog_only",
                reason="promotion_capacity_exhausted",
            )
        return FindingPromotionCapacityPlan(
            decisions=decisions,
            active_work_item_count=active_work_item_count,
        )
