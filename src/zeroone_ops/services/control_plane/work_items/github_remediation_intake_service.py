"""Provider-local intake for GitHub remediation work items."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import utc_now
from zeroone_ops.models.work_item import WorkItemClaim, WorkItemState
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.remediation_work_item_selection_service import (
    is_remediation_execution_eligible,
    remediation_execution_selection_key,
)
from zeroone_ops.services.remediation.remediation_execution_adapter import (
    control_plane_work_item_to_execution_target,
)


@dataclass(frozen=True)
class GitHubRemediationIntakeResult:
    """Capture selection and claim of one GitHub remediation work item."""

    selected_target: RemediationExecutionTarget | None
    claimed_work_item: WorkItemState | None
    issue: GitHubIssueInfo | None
    item_count: int
    message: str


class GitHubRemediationIntakeService:
    """Select and claim one authoritative GitHub remediation work item."""

    def __init__(
        self,
        *,
        work_item_service: GitHubWorkItemService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the GitHub work-item intake service."""
        self.work_item_service = work_item_service
        self.clock = clock or utc_now

    def select_and_claim(
        self,
        *,
        repository_id: str,
        persist: bool = True,
        run_id: str | None = None,
    ) -> GitHubRemediationIntakeResult:
        """Select the next eligible item and claim it when persistence is enabled."""
        work_items = self.work_item_service.list_open_work_items(repository_id=repository_id)
        candidates = [
            candidate
            for result in work_items
            if (candidate := self._candidate_from(result)) is not None
        ]
        if not candidates:
            return GitHubRemediationIntakeResult(
                selected_target=None,
                claimed_work_item=None,
                issue=None,
                item_count=len(work_items),
                message="No eligible approved GitHub remediation work items were found.",
            )

        selected = min(candidates, key=self._selection_key)
        if not persist:
            return GitHubRemediationIntakeResult(
                selected_target=control_plane_work_item_to_execution_target(
                    selected.work_item,
                    work_item_url=selected.issue.web_url,
                ),
                claimed_work_item=selected.work_item,
                issue=selected.issue,
                item_count=len(work_items),
                message="",
            )
        claimed = self.work_item_service.upsert_work_item(
            repository_id=repository_id,
            work_item=selected.work_item.model_copy(
                update={
                    "status": (
                        "review_revision_queued"
                        if selected.work_item.status == "review_revision_queued"
                        else "in_progress"
                    ),
                    "claim": WorkItemClaim(claimed_at=self.clock(), run_id=run_id),
                }
            ),
        )
        return GitHubRemediationIntakeResult(
            selected_target=control_plane_work_item_to_execution_target(
                claimed.work_item,
                work_item_url=claimed.issue.web_url,
            ),
            claimed_work_item=claimed.work_item,
            issue=claimed.issue,
            item_count=len(work_items),
            message="",
        )

    def _candidate_from(
        self,
        result: GitHubWorkItemLookupResult,
    ) -> GitHubWorkItemLookupResult | None:
        """Return one execution-ready approved remediation record when eligible."""
        return result if is_remediation_execution_eligible(result.work_item) else None

    def _selection_key(
        self,
        result: GitHubWorkItemLookupResult,
    ) -> tuple[int, int, datetime, int]:
        """Return the stable priority order for eligible GitHub work items."""
        return remediation_execution_selection_key(
            result.work_item,
            created_at=result.issue.created_at,
            provider_issue_number=result.issue.number,
        )
