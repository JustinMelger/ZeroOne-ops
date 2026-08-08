"""Poll and process authorized GitLab recovery notes on work-item issues."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.state import FailureDetails, FailureStage, RunRecord, RunStatus, utc_now
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_recovery_service import (
    GitLabWorkItemRecoveryProcessResult,
    GitLabWorkItemRecoveryService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary


@dataclass(frozen=True)
class GitLabWorkItemRecoveryPollResult:
    """Summarize one bounded GitLab recovery-note polling pass."""

    work_item_count: int
    note_count: int
    authorized_note_count: int
    matched_command_count: int
    accepted_command_count: int
    rejected_command_count: int


class GitLabWorkItemRecoveryRunner:
    """Process recovery notes from all open authoritative GitLab work items."""

    def __init__(
        self,
        *,
        recovery_service: GitLabWorkItemRecoveryService,
        work_item_service: GitLabWorkItemService,
        policy_service: FindingWorkflowPolicyService,
        run_state_service: RunStateService,
    ) -> None:
        """Initialize bounded GitLab recovery polling dependencies."""
        self.recovery_service = recovery_service
        self.work_item_service = work_item_service
        self.policy_service = policy_service
        self.run_state_service = run_state_service

    def run(
        self,
        *,
        project_id: str,
        policy_state: PolicyState,
        record: RunRecord,
        active_dry_run: bool,
        execution_mode: str,
    ) -> RunSummary:
        """Process new authorized recovery commands on open GitLab work-item issues."""
        if not active_dry_run and execution_mode != "ci":
            message = (
                "GitLab recovery live execution is only supported in CI mode. "
                "Use --dry-run locally."
            )
            return self.run_state_service.fail_run(
                record=record,
                error_message=message,
                failure=FailureDetails(stage=FailureStage.DASHBOARD_UPDATE, message=message),
            )
        counts = _RecoveryCounts()
        for existing in self.work_item_service.list_open_work_items(project_id=project_id):
            result = self.recovery_service.process(
                project_id=project_id,
                existing=existing,
                policy_eligible=self.policy_service.is_work_item_eligible(
                    work_item=existing.work_item,
                    policy_state=policy_state,
                ),
                persist=not active_dry_run,
            )
            counts.record(result)
        record.status = RunStatus.SYNCED if counts.accepted_command_count else RunStatus.NO_ISSUE
        record.updated_at = utc_now()
        self.run_state_service.state_store.save(self.run_state_service.state)
        prefix = "Dry-run would process" if active_dry_run else "Processed"
        return self.run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=(
                f"{prefix} {counts.note_count} GitLab work-item notes across "
                f"{counts.work_item_count} work items ({counts.authorized_note_count} authorized, "
                f"{counts.matched_command_count} recovery commands, "
                f"{counts.accepted_command_count} accepted, "
                f"{counts.rejected_command_count} rejected)."
            ),
        )


@dataclass
class _RecoveryCounts:
    work_item_count: int = 0
    note_count: int = 0
    authorized_note_count: int = 0
    matched_command_count: int = 0
    accepted_command_count: int = 0
    rejected_command_count: int = 0

    def record(self, result: GitLabWorkItemRecoveryProcessResult) -> None:
        """Accumulate one provider-local recovery processing result."""
        self.work_item_count += 1
        self.note_count += result.note_count
        self.authorized_note_count += result.authorized_note_count
        self.matched_command_count += result.matched_command_count
        self.accepted_command_count += result.accepted_command_count
        self.rejected_command_count += result.rejected_command_count
