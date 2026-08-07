"""Run GitLab dashboard remediation recovery command processing."""

from __future__ import annotations

from zeroone_ops.models.state import FailureDetails, FailureStage, RunRecord, RunStatus, utc_now
from zeroone_ops.services.dashboard.dashboard_recovery_service import DashboardRecoveryService
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary


class DashboardRecoveryRunner:
    """Run one provider-local GitLab dashboard recovery processing pass."""

    def __init__(
        self,
        *,
        recovery_service: DashboardRecoveryService,
        run_state_service: RunStateService,
    ) -> None:
        """Initialize the runner."""
        self.recovery_service = recovery_service
        self.run_state_service = run_state_service

    def run(
        self,
        *,
        project_id: str,
        record: RunRecord,
        active_dry_run: bool,
        execution_mode: str,
    ) -> RunSummary:
        """Process authorized recovery commands on the GitLab dashboard issue."""
        if not active_dry_run and execution_mode != "ci":
            message = "GitLab recovery live execution is only supported in CI mode."
            return self.run_state_service.fail_run(
                record=record,
                error_message=message,
                failure=FailureDetails(stage=FailureStage.DASHBOARD_UPDATE, message=message),
            )
        result = self.recovery_service.process(
            project_id=project_id,
            run_id=record.run_id,
            persist=not active_dry_run,
        )
        record.status = RunStatus.SYNCED if result.accepted_command_count else RunStatus.NO_ISSUE
        record.updated_at = utc_now()
        self.run_state_service.state_store.save(self.run_state_service.state)
        prefix = "Dry-run would process" if active_dry_run else "Processed"
        return self.run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=(
                f"{prefix} {result.note_count} GitLab dashboard notes "
                f"({result.authorized_note_count} authorized, "
                f"{result.matched_command_count} recovery commands, "
                f"{result.accepted_command_count} accepted, "
                f"{result.rejected_command_count} rejected)."
            ),
        )
