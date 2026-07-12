"""Shared promotion decisions for remediation work-item control-plane materialization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.remediation import RemediationWorkItem

RemediationWorkItemPromotionDisposition = Literal["promote", "backlog_only"]
RemediationWorkItemPromotionReason = Literal[
    "selected_for_remediation",
    "blocked_requires_attention",
    "linked_change_request_open",
    "default_backlog_only",
]


@dataclass(frozen=True)
class RemediationWorkItemPromotionContext:
    """Carry the bounded shared context for one promotion decision."""

    selected_for_remediation: bool = False
    blocked_requires_attention: bool = False
    linked_change_request_open: bool = False


@dataclass(frozen=True)
class RemediationWorkItemPromotionDecision:
    """Describe whether one remediation work item needs durable coordination."""

    disposition: RemediationWorkItemPromotionDisposition
    reason: RemediationWorkItemPromotionReason


class RemediationWorkItemPromotionService:
    """Apply the first shared promotion rule for remediation work items."""

    def decide(
        self,
        *,
        work_item: RemediationWorkItem,
        context: RemediationWorkItemPromotionContext,
    ) -> RemediationWorkItemPromotionDecision:
        """Return whether the candidate should become an authoritative work item."""
        _ = work_item
        if context.selected_for_remediation:
            return RemediationWorkItemPromotionDecision(
                disposition="promote",
                reason="selected_for_remediation",
            )
        if context.blocked_requires_attention:
            return RemediationWorkItemPromotionDecision(
                disposition="promote",
                reason="blocked_requires_attention",
            )
        if context.linked_change_request_open:
            return RemediationWorkItemPromotionDecision(
                disposition="promote",
                reason="linked_change_request_open",
            )
        return RemediationWorkItemPromotionDecision(
            disposition="backlog_only",
            reason="default_backlog_only",
        )
