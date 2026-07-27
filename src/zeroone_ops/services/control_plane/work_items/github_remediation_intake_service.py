"""Provider-local intake for GitHub remediation work items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.remediation.remediation_execution_adapter import (
    control_plane_work_item_to_execution_target,
)

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


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

    def __init__(self, *, work_item_service: GitHubWorkItemService) -> None:
        """Initialize the GitHub work-item intake service."""
        self.work_item_service = work_item_service

    def select_and_claim(
        self,
        *,
        repository_id: str,
        persist: bool = True,
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
                selected_target=control_plane_work_item_to_execution_target(selected.work_item),
                claimed_work_item=selected.work_item,
                issue=selected.issue,
                item_count=len(work_items),
                message="",
            )
        claimed = self.work_item_service.upsert_work_item(
            repository_id=repository_id,
            work_item=selected.work_item.model_copy(update={"status": "in_progress"}),
        )
        return GitHubRemediationIntakeResult(
            selected_target=control_plane_work_item_to_execution_target(claimed.work_item),
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
        result: GitHubWorkItemLookupResult,
    ) -> tuple[int, datetime, int]:
        """Return the stable priority order for eligible GitHub work items."""
        severity = result.work_item.severity or "low"
        created_at = result.issue.created_at or datetime.max.replace(tzinfo=UTC)
        return (
            _SEVERITY_ORDER.get(severity.lower(), len(_SEVERITY_ORDER)),
            created_at,
            result.issue.number,
        )


def _is_safe_repository_path(file_path: str | None) -> bool:
    """Return whether one stored work-item path remains within the repository."""
    if not file_path:
        return False
    path = PurePosixPath(file_path)
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts
