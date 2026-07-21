"""Shared default workflow policy for normalized findings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.finding import NormalizedFinding

FindingWorkflowDisposition = Literal["queue_candidate"]
FindingWorkflowReason = Literal["default_queue_candidate"]


@dataclass(frozen=True)
class FindingWorkflowDecision:
    """Describe the shared default workflow decision for one finding."""

    disposition: FindingWorkflowDisposition
    reason: FindingWorkflowReason


class FindingWorkflowPolicyService:
    """Apply the first shared queueing rule for normalized findings."""

    def decide(self, *, finding: NormalizedFinding) -> FindingWorkflowDecision:
        """Return the shared default workflow decision for one normalized finding."""
        _ = finding
        return FindingWorkflowDecision(
            disposition="queue_candidate",
            reason="default_queue_candidate",
        )
