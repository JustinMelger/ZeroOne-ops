"""Provider-local GitHub publication for promoted normalized findings."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.finding_sync import FindingSyncResult
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.services.control_plane.work_items.finding_sync_coordinator import (
    FindingSyncCoordinator,
)
from zeroone_ops.services.control_plane.work_items.github_finding_sync_storage import (
    GitHubFindingSyncStorage,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.intake.finding_policy_reconciliation_service import (
    FindingPolicyReconciliationService,
)
from zeroone_ops.services.intake.finding_promotion_capacity_service import (
    FindingPromotionCapacityService,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)

LOGGER = logging.getLogger(__name__)

GitHubFindingSyncResult = FindingSyncResult


class GitHubFindingSyncService:
    """Publish policy-promoted normalized findings as GitHub work-item issues."""

    def __init__(
        self,
        *,
        work_item_service: GitHubWorkItemService,
        workflow_policy_service: FindingWorkflowPolicyService | None = None,
        promotion_capacity_service: FindingPromotionCapacityService | None = None,
        policy_reconciliation_service: FindingPolicyReconciliationService | None = None,
    ) -> None:
        """Initialize provider-local publication over shared finding policy."""
        self.work_item_service = work_item_service
        self.workflow_policy_service = workflow_policy_service or FindingWorkflowPolicyService()
        self.promotion_capacity_service = (
            promotion_capacity_service
            or FindingPromotionCapacityService(self.workflow_policy_service)
        )
        self.policy_reconciliation_service = (
            policy_reconciliation_service or FindingPolicyReconciliationService()
        )

    def sync(
        self,
        *,
        repository_id: str,
        findings: list[NormalizedFinding],
        policy_state: PolicyState,
        managed_source_ids: set[str] | None = None,
        max_active_work_items: int = 10,
        source_priorities: Mapping[str, int] | None = None,
        persist: bool = True,
        run_id: str = "finding-sync",
    ) -> FindingSyncResult:
        """Upsert only findings promoted by the shared workflow policy."""
        return FindingSyncCoordinator(
            storage=GitHubFindingSyncStorage(self.work_item_service),
            logger=LOGGER,
            provider_label="GitHub",
            workflow_policy_service=self.workflow_policy_service,
            promotion_capacity_service=self.promotion_capacity_service,
            policy_reconciliation_service=self.policy_reconciliation_service,
        ).sync(
            repository_scope=repository_id,
            findings=findings,
            policy_state=policy_state,
            managed_source_ids=managed_source_ids,
            max_active_work_items=max_active_work_items,
            source_priorities=source_priorities,
            persist=persist,
            run_id=run_id,
        )
