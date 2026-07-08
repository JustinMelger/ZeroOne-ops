"""GitHub policy-processing workflow runner."""

from __future__ import annotations

from zeroone_ops.models.state import (
    FailureDetails,
    FailureStage,
    RunRecord,
    RunStatus,
    utc_now,
)
from zeroone_ops.services.control_plane.github_policy_issue_service import (
    GitHubPolicyIssueProcessResult,
    GitHubPolicyIssueService,
)
from zeroone_ops.services.shared.run_state_service import RunStateService, RunSummary


class GitHubPolicyProcessingRunner:
    """Run dedicated GitHub policy processing with injected dependencies."""

    def __init__(
        self,
        *,
        policy_issue_service: GitHubPolicyIssueService,
        run_state_service: RunStateService,
    ) -> None:
        """Initialize the GitHub policy-processing runner."""
        self.policy_issue_service = policy_issue_service
        self.run_state_service = run_state_service

    def run(
        self,
        *,
        repository_id: str,
        record: RunRecord,
        active_dry_run: bool,
        execution_mode: str,
    ) -> RunSummary:
        """Run one GitHub policy-processing workflow."""
        if not active_dry_run and execution_mode != "ci":
            message = (
                "GitHub policy live execution is only supported in CI mode. Use --dry-run locally."
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
            repository_id=repository_id,
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
        process_result: GitHubPolicyIssueProcessResult,
        active_dry_run: bool,
    ) -> str:
        """Build one GitHub policy-processing summary."""
        prefix = "Dry-run would process" if active_dry_run else "Processed"
        if process_result.issue_created or (active_dry_run and process_result.issue_missing):
            created_text = "created the GitHub policy issue and "
        else:
            created_text = ""
        change_text = (
            "updated GitHub policy issue state."
            if process_result.issue_changed
            else "found no GitHub policy change."
        )
        return (
            f"{prefix} {process_result.comment_count} GitHub policy comments "
            f"({process_result.authorized_comment_count} authorized, "
            f"{process_result.matched_prefix_count} prefixed, "
            f"{process_result.accepted_action_count} accepted, "
            f"{process_result.rejected_prefix_count} rejected) and "
            f"{created_text}{change_text}"
        )
