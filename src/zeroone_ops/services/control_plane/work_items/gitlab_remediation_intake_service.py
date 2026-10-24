"""Provider-local intake for GitLab remediation work items."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.remediation_intake import RemediationIntakeRecord
from zeroone_ops.models.state import utc_now
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.remediation_intake_coordinator import (
    RemediationIntakeCoordinator,
)
from zeroone_ops.services.control_plane.work_items.work_item_state_merge import (
    merge_batch_claim_state,
)


@dataclass(frozen=True)
class GitLabRemediationIntakeResult:
    """Capture selection and claim of one GitLab remediation work item."""

    selected_target: RemediationExecutionTarget | None
    claimed_work_item: WorkItemState | None
    issue: GitLabIssueInfo | None
    item_count: int
    message: str
    batch_policy: PolicyState | None = None


class GitLabRemediationIntakeService:
    """Select and claim one authoritative GitLab remediation work item."""

    def __init__(
        self,
        *,
        work_item_service: GitLabWorkItemService,
        clock: Callable[[], datetime] | None = None,
        load_batch_policy: Callable[[], PolicyState] | None = None,
    ) -> None:
        """Initialize the GitLab work-item intake service."""
        self.work_item_service = work_item_service
        self.clock = clock or utc_now
        self.load_batch_policy = load_batch_policy

    def select_and_claim(
        self,
        *,
        project_id: str,
        persist: bool = True,
        run_id: str | None = None,
    ) -> GitLabRemediationIntakeResult:
        """Select the next eligible item and claim it when persistence is enabled."""
        work_items = self.work_item_service.list_open_work_items(project_id=project_id)
        issues = {result.issue.iid: result.issue for result in work_items}

        selected_states = {r.work_item.identity_key: r.work_item for r in work_items}

        coordinator = RemediationIntakeCoordinator(
            clock=self.clock, load_batch_policy=self.load_batch_policy
        )

        def persist_claim(work_item: WorkItemState) -> RemediationIntakeRecord:
            if work_item.batch is None:
                claimed = self.work_item_service.upsert_work_item(
                    project_id=project_id, work_item=work_item
                )
            else:
                current = self.work_item_service.find_open_work_item_by_source(
                    project_id=project_id, kind=work_item.kind, source=work_item.source
                )
                if current is None:
                    raise RuntimeError("Selected open batch is unavailable; no claim was written.")
                merged = merge_batch_claim_state(
                    current.work_item, work_item, expected=selected_states[work_item.identity_key]
                )
                claimed = self.work_item_service.update_existing_work_item(
                    project_id=project_id,
                    existing=current,
                    work_item=merged,
                    policy_state=coordinator.batch_policy,
                )
            issues[claimed.issue.iid] = claimed.issue
            return self._record_from(work_item=claimed.work_item, issue=claimed.issue)

        outcome = coordinator.select_and_claim(
            records=[
                self._record_from(work_item=result.work_item, issue=result.issue)
                for result in work_items
            ],
            persist_work_item=persist_claim,
            persist=persist,
            run_id=run_id,
        )
        selected = outcome.selected_record
        return GitLabRemediationIntakeResult(
            selected_target=outcome.selected_target,
            claimed_work_item=selected.work_item if selected is not None else None,
            issue=issues[selected.issue_number] if selected is not None else None,
            item_count=outcome.item_count,
            batch_policy=outcome.batch_policy,
            message=(
                ""
                if selected is not None
                else "No eligible approved GitLab remediation work items were found."
            ),
        )

    def _record_from(
        self, *, work_item: WorkItemState, issue: GitLabIssueInfo
    ) -> RemediationIntakeRecord:
        """Normalize parsed state and GitLab issue metadata for shared intake."""
        return RemediationIntakeRecord(
            work_item=work_item,
            issue_number=issue.iid,
            issue_url=issue.web_url,
            created_at=issue.created_at,
        )
