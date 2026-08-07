"""Run GitHub work-item recovery processing from issue-comment workflow context."""

from __future__ import annotations

from zeroone_ops.models.state import FailureDetails, FailureStage, RunRecord, RunStatus, utc_now
from zeroone_ops.services.control_plane.work_items.github_work_item_recovery_service import (
    GitHubWorkItemRecoveryProcessResult,
    GitHubWorkItemRecoveryService,
)
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary


class GitHubWorkItemRecoveryRunner:
    """Run one provider-local GitHub recovery command processing pass."""

    def __init__(
        self,
        *,
        recovery_service: GitHubWorkItemRecoveryService,
        run_state_service: RunStateService,
    ) -> None:
        """Initialize the runner."""
        self.recovery_service = recovery_service
        self.run_state_service = run_state_service

    def run(
        self,
        *,
        repository_id: str,
        issue_number: int,
        comment_id: int,
        policy_eligible: bool,
        record: RunRecord,
        active_dry_run: bool,
        execution_mode: str,
    ) -> RunSummary:
        """Process recovery commands on the current GitHub work-item issue."""
        if not active_dry_run and execution_mode != "ci":
            return self.run_state_service.fail_run(
                record=record,
                error_message="GitHub recovery live execution is only supported in CI mode.",
                failure=FailureDetails(
                    stage=FailureStage.DASHBOARD_UPDATE,
                    message="GitHub recovery live execution is only supported in CI mode.",
                ),
            )
        result = self.recovery_service.process(
            repository_id=repository_id,
            issue_number=issue_number,
            comment_id=comment_id,
            policy_eligible=policy_eligible,
            persist=not active_dry_run,
        )
        record.status = RunStatus.SYNCED if result.accepted_command_count else RunStatus.NO_ISSUE
        record.updated_at = utc_now()
        self.run_state_service.state_store.save(self.run_state_service.state)
        return self.run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            work_item_id=None if result.work_item is None else result.work_item.work_item_id,
            message=_build_message(result=result, active_dry_run=active_dry_run),
        )


def _build_message(
    *,
    result: GitHubWorkItemRecoveryProcessResult,
    active_dry_run: bool,
) -> str:
    """Build one concise recovery command-processing outcome message."""
    prefix = "Dry-run would process" if active_dry_run else "Processed"
    if result.issue is None:
        return "No authoritative GitHub work item matched the current issue."
    return (
        f"{prefix} {result.comment_count} GitHub work-item comments "
        f"({result.authorized_comment_count} authorized, "
        f"{result.matched_command_count} recovery commands, "
        f"{result.accepted_command_count} accepted, "
        f"{result.rejected_command_count} rejected)."
    )
