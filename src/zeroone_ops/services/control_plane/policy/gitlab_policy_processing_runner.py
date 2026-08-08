"""GitLab policy-processing workflow runner."""

from __future__ import annotations

from zeroone_ops.models.state import (
    FailureDetails,
    FailureStage,
    RunRecord,
    RunStatus,
    utc_now,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_service import (
    GitLabPolicyIssueProcessResult,
    GitLabPolicyIssueService,
)
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary


class GitLabPolicyProcessingRunner:
    """Run dedicated GitLab policy processing with injected dependencies."""

    def __init__(
        self,
        *,
        policy_issue_service: GitLabPolicyIssueService,
        run_state_service: RunStateService,
    ) -> None:
        """Initialize the GitLab policy-processing runner."""
        self.policy_issue_service = policy_issue_service
        self.run_state_service = run_state_service

    def run(
        self,
        *,
        project_id: str,
        record: RunRecord,
        active_dry_run: bool,
        execution_mode: str,
    ) -> RunSummary:
        """Run one GitLab policy-processing workflow."""
        if not active_dry_run and execution_mode != "ci":
            message = (
                "GitLab policy live execution is only supported in CI mode. Use --dry-run locally."
            )
            return self.run_state_service.fail_run(
                record=record,
                error_message=message,
                failure=FailureDetails(
                    stage=FailureStage.DASHBOARD_UPDATE,
                    message=message,
                ),
            )

        process_result = self.policy_issue_service.process_policy(
            project_id=project_id,
            persist=not active_dry_run,
        )
        record.status = RunStatus.SYNCED if process_result.issue_changed else RunStatus.NO_ISSUE
        record.updated_at = utc_now()
        self.run_state_service.state_store.save(self.run_state_service.state)
        return self.run_state_service.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=self._build_message(
                process_result=process_result,
                active_dry_run=active_dry_run,
            ),
        )

    def _build_message(
        self,
        *,
        process_result: GitLabPolicyIssueProcessResult,
        active_dry_run: bool,
    ) -> str:
        """Build one GitLab policy-processing summary."""
        prefix = "Dry-run would process" if active_dry_run else "Processed"
        if process_result.issue_created or (active_dry_run and process_result.issue_missing):
            created_text = "created the GitLab policy issue and "
        else:
            created_text = ""
        change_text = (
            "updated GitLab policy issue state."
            if process_result.issue_changed
            else "found no GitLab policy change."
        )
        return (
            f"{prefix} {process_result.note_count} GitLab policy notes "
            f"({process_result.authorized_note_count} authorized, "
            f"{process_result.matched_prefix_count} prefixed, "
            f"{process_result.accepted_action_count} accepted, "
            f"{process_result.rejected_prefix_count} rejected) and "
            f"{created_text}{change_text}"
        )
