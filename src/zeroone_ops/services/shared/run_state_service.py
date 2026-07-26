"""Run state orchestration service.

This module centralizes run-record and issue-state transitions.
"""

from __future__ import annotations

import logging

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.state import (
    AppState,
    FailureDetails,
    IssueState,
    RunRecord,
    RunStatus,
    utc_now,
)
from zeroone_ops.services.dashboard.dashboard_run_state_service import (
    DashboardRunStateService,
)
from zeroone_ops.services.shared.run_summary_builder import (
    RunSummary,
    RunSummaryBuilder,
)
from zeroone_ops.services.shared.state_store import StateStore

LOGGER = logging.getLogger(__name__)

__all__ = ["RunSummary", "RunStateService"]


class RunStateService:
    """Manage run lifecycle transitions and persistence.

    Args:
        config: Loaded application configuration.
        state_store: State store implementation.
        state: Mutable application state.
    """

    def __init__(self, config: AppConfig, state_store: StateStore, state: AppState) -> None:
        """Initialize the run state service.

        Args:
            config: Loaded application configuration.
            state_store: State store implementation.
            state: Mutable application state.
        """
        self.config = config
        self.state_store = state_store
        self.state = state
        self.summary_builder = RunSummaryBuilder(
            execution_mode=config.execution_mode,
            state_path=config.state.path,
        )
        self.dashboard = DashboardRunStateService(
            state_store=state_store,
            state=state,
            summary_builder=self.summary_builder,
        )

    def start_run(self, run_id: str) -> RunRecord:
        """Append and return a new started run record."""
        started_at = utc_now()
        record = RunRecord(
            run_id=run_id,
            status=RunStatus.STARTED,
            started_at=started_at,
            updated_at=started_at,
        )
        self.state_store.append_run(self.state, record)
        return record

    def mark_selected(self, *, record: RunRecord, issue_key: str) -> int:
        """Mark an issue as selected and return the current attempt count."""
        issue_state = self.state.issues.get(issue_key)
        attempt_count = issue_state.attempt_count if issue_state is not None else 0
        record.status = RunStatus.SELECTED
        record.issue_key = issue_key
        record.updated_at = utc_now()
        self.state.active_issue_key = issue_key
        self.state_store.set_issue_state(
            self.state,
            issue_key=issue_key,
            issue_state=IssueState(
                status=RunStatus.SELECTED.value,
                last_run_id=record.run_id,
                attempt_count=attempt_count,
            ),
        )
        return attempt_count

    def fail_run(
        self,
        *,
        record: RunRecord,
        error_message: str,
        failure: FailureDetails,
    ) -> RunSummary:
        """Persist a failed run that is not tied to a selected item."""
        record.status = RunStatus.FAILED
        record.error_message = error_message
        record.failure = failure
        record.updated_at = utc_now()
        self.state_store.save(self.state)
        return self.summary_builder.build(
            run_id=record.run_id,
            status=record.status,
            message=error_message,
        )

    def mark_fix_generated(
        self,
        *,
        record: RunRecord,
        issue_key: str,
        attempt_count: int,
        branch_name: str | None,
        commit_sha: str,
    ) -> None:
        """Persist a successful validated local commit."""
        record.status = RunStatus.FIX_GENERATED
        record.branch_name = branch_name
        record.commit_sha = commit_sha
        record.updated_at = utc_now()
        self.state_store.set_issue_state(
            self.state,
            issue_key=issue_key,
            issue_state=IssueState(
                status=RunStatus.FIX_GENERATED.value,
                last_run_id=record.run_id,
                attempt_count=attempt_count,
                branch_name=branch_name,
            ),
        )

    def mark_change_request_created(
        self,
        *,
        record: RunRecord,
        issue_key: str,
        attempt_count: int,
        branch_name: str | None,
        change_request_url: str,
    ) -> None:
        """Persist a created or reused change request."""
        record.status = RunStatus.CHANGE_REQUEST_CREATED
        record.branch_name = branch_name
        record.change_request_url = change_request_url
        record.updated_at = utc_now()
        self.state_store.set_issue_state(
            self.state,
            issue_key=issue_key,
            issue_state=IssueState(
                status=RunStatus.CHANGE_REQUEST_CREATED.value,
                last_run_id=record.run_id,
                attempt_count=attempt_count,
                branch_name=branch_name,
                change_request_url=change_request_url,
            ),
        )

    def fail_issue(
        self,
        *,
        record: RunRecord,
        issue_key: str,
        attempt_count: int,
        error_message: str,
        failure: FailureDetails,
    ) -> RunSummary:
        """Persist a failed issue execution and return the run summary."""
        record.status = RunStatus.FAILED
        record.error_message = error_message
        record.failure = failure
        record.updated_at = utc_now()
        self.state_store.set_issue_state(
            self.state,
            issue_key=issue_key,
            issue_state=IssueState(
                status=RunStatus.FAILED.value,
                last_run_id=record.run_id,
                attempt_count=attempt_count,
                branch_name=record.branch_name,
                change_request_url=record.change_request_url,
                last_error=error_message,
                failure=failure,
            ),
        )
        self.state_store.save(self.state)
        LOGGER.error(
            "run failed",
            extra={
                "run_id": record.run_id,
                "issue_key": issue_key,
                "stage": failure.stage.value,
                "branch_name": record.branch_name,
                "commit_sha": record.commit_sha,
                "failed_command": failure.failed_command,
                "exit_code": failure.exit_code,
            },
        )
        return self.summary_builder.build(
            run_id=record.run_id,
            status=record.status,
            message=error_message,
        )

    def reject_issue(
        self,
        *,
        record: RunRecord,
        issue_key: str,
        attempt_count: int,
        branch_name: str | None,
        message: str,
    ) -> RunSummary:
        """Persist a local approval rejection and return the run summary."""
        record.status = RunStatus.REJECTED
        record.branch_name = branch_name
        record.updated_at = utc_now()
        self.state_store.set_issue_state(
            self.state,
            issue_key=issue_key,
            issue_state=IssueState(
                status=RunStatus.REJECTED.value,
                last_run_id=record.run_id,
                attempt_count=attempt_count,
                branch_name=branch_name,
                last_error=message,
            ),
        )
        self.state_store.save(self.state)
        LOGGER.info(
            "run rejected",
            extra={
                "run_id": record.run_id,
                "issue_key": issue_key,
                "branch_name": branch_name,
            },
        )
        return self.summary_builder.build(
            run_id=record.run_id,
            status=record.status,
            message=message,
        )

    def finish_no_issue(self, *, record: RunRecord, message: str, issue_count: int) -> RunSummary:
        """Persist a no-issue result and return the run summary."""
        record.status = RunStatus.NO_ISSUE
        record.updated_at = utc_now()
        self.state.active_issue_key = None
        self.state_store.save(self.state)
        LOGGER.info(
            "run complete",
            extra={"run_id": record.run_id, "issue_count": issue_count},
        )
        return self.summary_builder.build(
            run_id=record.run_id,
            status=record.status,
            message=message,
        )

    def build_summary(
        self,
        *,
        run_id: str,
        status: RunStatus,
        message: str,
        issue_key: str | None = None,
        work_item_id: str | None = None,
        dashboard_item_id: str | None = None,
        branch_name: str | None = None,
        commit_sha: str | None = None,
        change_request_url: str | None = None,
        change_request_action: str | None = None,
    ) -> RunSummary:
        """Build a CLI-facing run summary."""
        return self.summary_builder.build(
            run_id=run_id,
            status=status,
            message=message,
            issue_key=issue_key,
            work_item_id=work_item_id,
            dashboard_item_id=dashboard_item_id,
            branch_name=branch_name,
            commit_sha=commit_sha,
            change_request_url=change_request_url,
            change_request_action=change_request_action,
        )
