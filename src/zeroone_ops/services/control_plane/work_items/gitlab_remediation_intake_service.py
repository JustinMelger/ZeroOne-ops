"""Provider-local intake for GitLab remediation work items."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import utc_now
from zeroone_ops.models.work_item import WorkItemClaim, WorkItemState
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.remediation.remediation_execution_adapter import (
    control_plane_work_item_to_execution_target,
)

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class GitLabRemediationIntakeResult:
    """Capture selection and claim of one GitLab remediation work item."""

    selected_target: RemediationExecutionTarget | None
    claimed_work_item: WorkItemState | None
    issue: GitLabIssueInfo | None
    item_count: int
    message: str


class GitLabRemediationIntakeService:
    """Select and claim one authoritative GitLab remediation work item."""

    def __init__(
        self,
        *,
        work_item_service: GitLabWorkItemService,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Initialize the GitLab work-item intake service."""
        self.work_item_service = work_item_service
        self.clock = clock or utc_now

    def select_and_claim(
        self,
        *,
        project_id: str,
        persist: bool = True,
        run_id: str | None = None,
    ) -> GitLabRemediationIntakeResult:
        """Select the next eligible item and claim it when persistence is enabled."""
        work_items = self.work_item_service.list_open_work_items(project_id=project_id)
        candidates = [
            candidate
            for result in work_items
            if (candidate := self._candidate_from(result)) is not None
        ]
        if not candidates:
            return GitLabRemediationIntakeResult(
                selected_target=None,
                claimed_work_item=None,
                issue=None,
                item_count=len(work_items),
                message="No eligible approved GitLab remediation work items were found.",
            )

        selected = min(candidates, key=self._selection_key)
        if not persist:
            return GitLabRemediationIntakeResult(
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
            project_id=project_id,
            work_item=selected.work_item.model_copy(
                update={
                    "status": "in_progress",
                    "claim": WorkItemClaim(claimed_at=self.clock(), run_id=run_id),
                }
            ),
        )
        return GitLabRemediationIntakeResult(
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
        result: GitLabWorkItemLookupResult,
    ) -> GitLabWorkItemLookupResult | None:
        """Return one execution-ready approved remediation record when eligible."""
        work_item = result.work_item
        if work_item.kind != "remediation" or work_item.status != "approved":
            return None
        if work_item.linked_change_request is not None:
            return None
        if not _is_safe_repository_path(work_item.file_path):
            return None
        return result

    def _selection_key(
        self,
        result: GitLabWorkItemLookupResult,
    ) -> tuple[int, datetime, int]:
        """Return the stable priority order for eligible GitLab work items."""
        severity = result.work_item.severity or "low"
        created_at = result.issue.created_at or datetime.max.replace(tzinfo=UTC)
        return (
            _SEVERITY_ORDER.get(severity.lower(), len(_SEVERITY_ORDER)),
            created_at,
            result.issue.iid,
        )


def _is_safe_repository_path(file_path: str | None) -> bool:
    """Return whether one stored work-item path remains within the repository."""
    if not file_path:
        return False
    path = PurePosixPath(file_path)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts
