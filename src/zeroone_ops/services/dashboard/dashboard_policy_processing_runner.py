"""Dashboard policy-processing workflow runner."""

from __future__ import annotations

from zeroone_ops.models.state import (
    FailureDetails,
    FailureStage,
    RunRecord,
    RunStatus,
    utc_now,
)
from zeroone_ops.services.dashboard.dashboard_policy_acknowledgement_service import (
    DashboardPolicyAcknowledgementResult,
    DashboardPolicyAcknowledgementService,
)
from zeroone_ops.services.dashboard.dashboard_service import (
    DashboardPolicyProcessResult,
    DashboardService,
)
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary


class DashboardPolicyProcessingRunner:
    """Run dedicated dashboard policy processing with injected dependencies."""

    def __init__(
        self,
        *,
        dashboard_service: DashboardService,
        run_state_service: RunStateService,
        acknowledgement_service: DashboardPolicyAcknowledgementService | None = None,
    ) -> None:
        """Initialize the dashboard policy-processing runner."""
        self.dashboard_service = dashboard_service
        self.run_state_service = run_state_service
        self.acknowledgement_service = (
            acknowledgement_service or DashboardPolicyAcknowledgementService()
        )

    def run(
        self,
        *,
        project_id: str,
        record: RunRecord,
        active_dry_run: bool,
        execution_mode: str,
    ) -> RunSummary:
        """Run one dashboard policy-processing workflow."""
        if not active_dry_run and execution_mode != "ci":
            message = (
                "Dashboard policy live execution is only supported in CI mode. "
                "Use --dry-run locally."
            )
            return self.run_state_service.fail_run(
                record=record,
                error_message=message,
                failure=FailureDetails(
                    stage=FailureStage.DASHBOARD_UPDATE,
                    message=message,
                ),
            )

        process_result = self.dashboard_service.process_policy(
            project_id=project_id,
            persist=not active_dry_run,
        )
        acknowledgement_result = self.acknowledgement_service.publish_acknowledgements(
            client=self.dashboard_service.client,
            project_id=project_id,
            issue_iid=process_result.document.issue_iid,
            notes=process_result.notes or [],
            parsed_results=process_result.parsed_results or [],
            initial_policy_state=process_result.initial_policy_state
            or process_result.document.policy_state,
            dry_run=active_dry_run,
        )
        if process_result.dashboard_changed:
            record.status = RunStatus.SYNCED
        else:
            record.status = RunStatus.NO_ISSUE
        record.updated_at = utc_now()
        self.run_state_service.state_store.save(self.run_state_service.state)
        return self.run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=self._build_message(
                process_result=process_result,
                acknowledgement_result=acknowledgement_result,
                active_dry_run=active_dry_run,
            ),
        )

    def _build_message(
        self,
        *,
        process_result: DashboardPolicyProcessResult,
        acknowledgement_result: DashboardPolicyAcknowledgementResult,
        active_dry_run: bool,
    ) -> str:
        """Build one dashboard policy-processing summary."""
        prefix = "Dry-run would process" if active_dry_run else "Processed"
        if process_result.issue_created or (active_dry_run and process_result.dashboard_missing):
            created_text = "created the dashboard and "
        else:
            created_text = ""
        change_text = (
            "updated dashboard policy state."
            if process_result.dashboard_changed
            else "found no dashboard policy change."
        )
        message = (
            f"{prefix} {process_result.note_count} dashboard notes "
            f"({process_result.matched_prefix_count} prefixed, "
            f"{process_result.accepted_action_count} accepted, "
            f"{process_result.rejected_prefix_count} rejected) and "
            f"{created_text}{change_text}"
        )
        if acknowledgement_result.needed_count == 0:
            return message
        ack_prefix = "Would publish" if active_dry_run else "Published"
        message = (
            f"{message} {ack_prefix} {acknowledgement_result.published_count} acknowledgements"
        )
        if acknowledgement_result.skipped_existing_count > 0:
            message = f"{message}, skipped {acknowledgement_result.skipped_existing_count} existing"
        if acknowledgement_result.failed_count > 0:
            message = (
                f"{message}, and failed to publish "
                f"{acknowledgement_result.failed_count} acknowledgements."
            )
            return message
        return f"{message}."
