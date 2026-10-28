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

LOGGER = logging.getLogger(__name__)

GitHubFindingSyncResult = FindingSyncResult


class GitHubFindingSyncService:
    """Publish policy-promoted normalized findings as GitHub work-item issues."""

    def __init__(
        self,
        *,
        work_item_service: GitHubWorkItemService,
    ) -> None:
        """Retain provider-local transport for shared sync composition."""
        self.work_item_service = work_item_service

    def sync(
        self,
        *,
        repository_id: str,
        findings: list[NormalizedFinding],
        policy_state: PolicyState,
        managed_source_ids: set[str] | None = None,
        max_active_work_items: int = 10,
        max_findings_per_work_item: int = 5,
        source_priorities: Mapping[str, int] | None = None,
        persist: bool = True,
        run_id: str = "finding-sync",
    ) -> FindingSyncResult:
        """Upsert only findings promoted by the shared workflow policy."""
        return FindingSyncCoordinator(
            storage=GitHubFindingSyncStorage(self.work_item_service, policy_state=policy_state),
            logger=LOGGER,
        ).sync(
            repository_scope=repository_id,
            findings=findings,
            policy_state=policy_state,
            managed_source_ids=managed_source_ids,
            max_active_work_items=max_active_work_items,
            max_findings_per_work_item=max_findings_per_work_item,
            source_priorities=source_priorities,
            persist=persist,
            run_id=run_id,
        )
