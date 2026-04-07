"""Run state orchestration service.

This module centralizes run-record and issue-state transitions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.state import (
    AppState,
    DashboardItemState,
    FailureDetails,
    IssueState,
    RunRecord,
    RunStatus,
    utc_now,
)
from ai_sonar_bot.services.state_store import StateStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunSummary:
    """Summarize a bot execution result."""

    run_id: str
    status: RunStatus
    message: str
    state_path: Path


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

    def mark_dashboard_selected(self, *, record: RunRecord, dashboard_item_id: str) -> None:
        """Mark one dashboard item as selected for remediation."""
        record.status = RunStatus.SELECTED
        record.dashboard_item_id = dashboard_item_id
        record.updated_at = utc_now()
        self.state.active_dashboard_item_id = dashboard_item_id
        self.state.dashboard_items[dashboard_item_id] = DashboardItemState(
            status=RunStatus.SELECTED.value,
            last_run_id=record.run_id,
        )

    def mark_dashboard_mr_created(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        branch_name: str | None,
        mr_url: str,
    ) -> None:
        """Persist a created or reused merge request for one dashboard item."""
        record.status = RunStatus.MR_CREATED
        record.dashboard_item_id = dashboard_item_id
        record.branch_name = branch_name
        record.mr_url = mr_url
        record.updated_at = utc_now()
        self.state.dashboard_items[dashboard_item_id] = DashboardItemState(
            status=RunStatus.MR_CREATED.value,
            last_run_id=record.run_id,
            branch_name=branch_name,
            mr_url=mr_url,
        )

    def fail_dashboard_item(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        error_message: str,
        failure: FailureDetails,
    ) -> RunSummary:
        """Persist a failed dashboard remediation run and return the summary."""
        record.status = RunStatus.FAILED
        record.dashboard_item_id = dashboard_item_id
        record.error_message = error_message
        record.failure = failure
        record.updated_at = utc_now()
        self.state.active_dashboard_item_id = None
        self.state.dashboard_items[dashboard_item_id] = DashboardItemState(
            status=RunStatus.FAILED.value,
            last_run_id=record.run_id,
            branch_name=record.branch_name,
            commit_sha=record.commit_sha,
            mr_url=record.mr_url,
            last_error=error_message,
        )
        self.state_store.save(self.state)
        return self.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=error_message,
        )

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
        return self.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=error_message,
        )

    def reject_dashboard_item(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        branch_name: str | None,
        message: str,
    ) -> RunSummary:
        """Persist a rejected dashboard remediation run and return the summary."""
        record.status = RunStatus.REJECTED
        record.dashboard_item_id = dashboard_item_id
        record.branch_name = branch_name
        record.updated_at = utc_now()
        self.state.active_dashboard_item_id = None
        self.state.dashboard_items[dashboard_item_id] = DashboardItemState(
            status=RunStatus.REJECTED.value,
            last_run_id=record.run_id,
            branch_name=branch_name,
            last_error=message,
        )
        self.state_store.save(self.state)
        return self.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=message,
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

    def mark_mr_created(
        self,
        *,
        record: RunRecord,
        issue_key: str,
        attempt_count: int,
        branch_name: str | None,
        mr_url: str,
    ) -> None:
        """Persist a created or reused merge request."""
        record.status = RunStatus.MR_CREATED
        record.branch_name = branch_name
        record.mr_url = mr_url
        record.updated_at = utc_now()
        self.state_store.set_issue_state(
            self.state,
            issue_key=issue_key,
            issue_state=IssueState(
                status=RunStatus.MR_CREATED.value,
                last_run_id=record.run_id,
                attempt_count=attempt_count,
                branch_name=branch_name,
                mr_url=mr_url,
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
                mr_url=record.mr_url,
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
        return self.build_summary(
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
        return self.build_summary(
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
        return self.build_summary(
            run_id=record.run_id,
            status=record.status,
            message=message,
        )

    def finish_success(self, *, record: RunRecord) -> None:
        """Persist a successful in-progress run state."""
        self.state.active_dashboard_item_id = None
        self.state_store.save(self.state)

    def build_summary(
        self,
        *,
        run_id: str,
        status: RunStatus,
        message: str,
        mr_url: str | None = None,
        mr_action: str | None = None,
    ) -> RunSummary:
        """Build a CLI-facing run summary."""
        summary = f"[{self.config.execution_mode}] {message}"
        if mr_url is not None:
            if mr_action is None:
                summary = f"{summary} Merge request: {mr_url}"
            else:
                summary = f"{summary} Merge request {mr_action}: {mr_url}"
        return RunSummary(
            run_id=run_id,
            status=status,
            message=summary,
            state_path=self.config.state.path,
        )
