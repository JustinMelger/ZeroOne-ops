"""Dashboard-specific run state transitions."""

from __future__ import annotations

from zeroone_ops.models.state import (
    AppState,
    DashboardItemState,
    FailureDetails,
    RunRecord,
    RunStatus,
    utc_now,
)
from zeroone_ops.services.shared.run_summary_builder import (
    RunSummary,
    RunSummaryBuilder,
)
from zeroone_ops.services.shared.state_store import StateStore


class DashboardRunStateService:
    """Persist dashboard item state transitions for remediation workflows."""

    def __init__(
        self,
        *,
        state_store: StateStore,
        state: AppState,
        summary_builder: RunSummaryBuilder,
    ) -> None:
        """Initialize the dashboard run state helper."""
        self.state_store = state_store
        self.state = state
        self.summary_builder = summary_builder

    def mark_selected(self, *, record: RunRecord, dashboard_item_id: str) -> None:
        """Mark one dashboard item as selected for remediation."""
        record.status = RunStatus.SELECTED
        record.dashboard_item_id = dashboard_item_id
        record.updated_at = utc_now()
        self.state.active_dashboard_item_id = dashboard_item_id
        self.state.dashboard_items[dashboard_item_id] = DashboardItemState(
            status=RunStatus.SELECTED.value,
            last_run_id=record.run_id,
        )

    def mark_change_request_created(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        branch_name: str | None,
        change_request_url: str,
    ) -> None:
        """Persist a created or reused change request for one dashboard item."""
        record.status = RunStatus.CHANGE_REQUEST_CREATED
        record.dashboard_item_id = dashboard_item_id
        record.branch_name = branch_name
        record.change_request_url = change_request_url
        record.updated_at = utc_now()
        self.state.dashboard_items[dashboard_item_id] = DashboardItemState(
            status=RunStatus.CHANGE_REQUEST_CREATED.value,
            last_run_id=record.run_id,
            branch_name=branch_name,
            change_request_url=change_request_url,
        )

    def mark_mr_created(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        branch_name: str | None,
        mr_url: str,
    ) -> None:
        """Persist a created or reused merge request through the neutral helper."""
        self.mark_change_request_created(
            record=record,
            dashboard_item_id=dashboard_item_id,
            branch_name=branch_name,
            change_request_url=mr_url,
        )

    def mark_done(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        branch_name: str | None = None,
        commit_sha: str | None = None,
        change_request_url: str | None = None,
        mr_url: str | None = None,
    ) -> None:
        """Persist one dashboard item as no longer requiring remediation."""
        if change_request_url is None:
            change_request_url = mr_url
        record.dashboard_item_id = dashboard_item_id
        record.branch_name = branch_name
        record.commit_sha = commit_sha
        record.change_request_url = change_request_url
        record.updated_at = utc_now()
        self.state.active_dashboard_item_id = None
        self.state.dashboard_items[dashboard_item_id] = DashboardItemState(
            status="done",
            last_run_id=record.run_id,
            branch_name=branch_name,
            commit_sha=commit_sha,
            change_request_url=change_request_url,
        )

    def mark_reopened(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        branch_name: str | None = None,
        commit_sha: str | None = None,
        change_request_url: str | None = None,
        mr_url: str | None = None,
    ) -> None:
        """Persist one dashboard item as reopened for future remediation."""
        if change_request_url is None:
            change_request_url = mr_url
        record.dashboard_item_id = dashboard_item_id
        record.branch_name = branch_name
        record.commit_sha = commit_sha
        record.change_request_url = change_request_url
        record.updated_at = utc_now()
        self.state.active_dashboard_item_id = None
        self.state.dashboard_items[dashboard_item_id] = DashboardItemState(
            status="open",
            last_run_id=record.run_id,
            branch_name=branch_name,
            commit_sha=commit_sha,
            change_request_url=change_request_url,
        )

    def mark_failed(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        error_message: str,
        branch_name: str | None = None,
        commit_sha: str | None = None,
        change_request_url: str | None = None,
        mr_url: str | None = None,
    ) -> None:
        """Persist one dashboard item as failed without aborting the whole run."""
        if change_request_url is None:
            change_request_url = mr_url
        record.dashboard_item_id = dashboard_item_id
        record.branch_name = branch_name
        record.commit_sha = commit_sha
        record.change_request_url = change_request_url
        record.updated_at = utc_now()
        self.state.active_dashboard_item_id = None
        self.state.dashboard_items[dashboard_item_id] = DashboardItemState(
            status=RunStatus.FAILED.value,
            last_run_id=record.run_id,
            branch_name=branch_name,
            commit_sha=commit_sha,
            change_request_url=change_request_url,
            last_error=error_message,
        )

    def fail_item(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        error_message: str,
        failure: FailureDetails,
    ) -> RunSummary:
        """Persist a failed dashboard run and return the summary."""
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
            change_request_url=record.change_request_url,
            last_error=error_message,
        )
        self.state_store.save(self.state)
        return self.summary_builder.build(
            run_id=record.run_id,
            status=record.status,
            message=error_message,
            dashboard_item_id=dashboard_item_id,
            branch_name=record.branch_name,
            commit_sha=record.commit_sha,
            change_request_url=record.change_request_url,
        )

    def reject_item(
        self,
        *,
        record: RunRecord,
        dashboard_item_id: str,
        branch_name: str | None,
        message: str,
    ) -> RunSummary:
        """Persist a rejected dashboard run and return the summary."""
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
        return self.summary_builder.build(
            run_id=record.run_id,
            status=record.status,
            message=message,
            dashboard_item_id=dashboard_item_id,
            branch_name=record.branch_name,
            commit_sha=record.commit_sha,
            change_request_url=record.change_request_url,
        )

    def finish_success(self) -> None:
        """Persist a successful in-progress dashboard run state."""
        self.state.active_dashboard_item_id = None
        self.state_store.save(self.state)
