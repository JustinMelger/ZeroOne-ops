"""Dashboard lifecycle updates for remediation runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ai_sonar_bot.models.dashboard import DashboardDocument, DashboardItem
from ai_sonar_bot.services.dashboard_service import DashboardService


@dataclass(frozen=True)
class DashboardRemediationUpdateResult:
    """Capture the result of one remediation dashboard update."""

    dashboard_issue_url: str | None = None
    updated_item: DashboardItem | None = None
    error_message: str | None = None


class DashboardRemediationUpdater:
    """Own remediation lifecycle transitions on the dashboard."""

    def __init__(self, dashboard_service: DashboardService) -> None:
        """Initialize the updater."""
        self.dashboard_service = dashboard_service

    def mark_in_progress(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
    ) -> DashboardRemediationUpdateResult:
        """Mark one dashboard item in progress."""
        return self._update_item(
            project_id=project_id,
            dashboard_item_id=dashboard_item_id,
            status="in_progress",
            run_id=run_id,
        )

    def mark_mr_opened(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        branch_name: str,
        merge_request_url: str,
        commit_sha: str,
        merge_request_iid: int | None = None,
    ) -> DashboardRemediationUpdateResult:
        """Mark one dashboard item as having an open merge request."""
        return self._update_item(
            project_id=project_id,
            dashboard_item_id=dashboard_item_id,
            status="mr_opened",
            run_id=run_id,
            branch_name=branch_name,
            merge_request_url=merge_request_url,
            merge_request_iid=merge_request_iid,
            commit_sha=commit_sha,
        )

    def mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
    ) -> DashboardRemediationUpdateResult:
        """Mark one dashboard item as failed."""
        return self._update_item(
            project_id=project_id,
            dashboard_item_id=dashboard_item_id,
            status="failed",
            run_id=run_id,
            log_excerpt=error_message,
        )

    def mark_rejected(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        rejection_reason: str,
    ) -> DashboardRemediationUpdateResult:
        """Mark one dashboard item as rejected."""
        return self._update_item(
            project_id=project_id,
            dashboard_item_id=dashboard_item_id,
            status="rejected",
            run_id=run_id,
            log_excerpt=rejection_reason,
        )

    def mark_done(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        summary: str | None = None,
    ) -> DashboardRemediationUpdateResult:
        """Mark one dashboard item done."""
        return self._update_item(
            project_id=project_id,
            dashboard_item_id=dashboard_item_id,
            status="done",
            run_id=run_id,
            log_excerpt=summary,
        )

    def _update_item(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        status: str,
        run_id: str,
        branch_name: str | None = None,
        merge_request_url: str | None = None,
        merge_request_iid: int | None = None,
        commit_sha: str | None = None,
        log_excerpt: str | None = None,
    ) -> DashboardRemediationUpdateResult:
        """Load, update, and persist one dashboard item."""
        try:
            document = self.dashboard_service.load_or_create(project_id=project_id)
            current_item = self._require_item(document, dashboard_item_id)
            if self._is_idempotent_update(
                current_item=current_item,
                status=status,
                run_id=run_id,
                branch_name=branch_name,
                merge_request_url=merge_request_url,
                merge_request_iid=merge_request_iid,
                commit_sha=commit_sha,
                log_excerpt=log_excerpt,
            ):
                return DashboardRemediationUpdateResult(
                    dashboard_issue_url=document.issue_url,
                    updated_item=current_item,
                )
            updated_item = current_item.model_copy(
                update={
                    "status": status,
                    "last_run_id": run_id,
                    "status_updated_at": datetime.now(UTC),
                    "branch_name": (
                        branch_name if branch_name is not None else current_item.branch_name
                    ),
                    "merge_request_url": (
                        merge_request_url
                        if merge_request_url is not None
                        else current_item.merge_request_url
                    ),
                    "merge_request_iid": (
                        merge_request_iid
                        if merge_request_iid is not None
                        else current_item.merge_request_iid
                    ),
                    "commit_sha": commit_sha if commit_sha is not None else current_item.commit_sha,
                    "log_excerpt": (
                        log_excerpt if log_excerpt is not None else current_item.log_excerpt
                    ),
                }
            )
            updated_document = self.dashboard_service.upsert_items(
                project_id=project_id,
                items=[updated_item],
            )
        except Exception as error:  # pragma: no cover - defensive orchestration guard
            return DashboardRemediationUpdateResult(
                error_message=f"Dashboard remediation update failed: {error}",
            )
        persisted_item = updated_document.items_by_id().get(dashboard_item_id, updated_item)
        return DashboardRemediationUpdateResult(
            dashboard_issue_url=updated_document.issue_url,
            updated_item=persisted_item,
        )

    def _is_idempotent_update(
        self,
        *,
        current_item: DashboardItem,
        status: str,
        run_id: str,
        branch_name: str | None,
        merge_request_url: str | None,
        merge_request_iid: int | None,
        commit_sha: str | None,
        log_excerpt: str | None,
    ) -> bool:
        """Return whether one lifecycle update would be a no-op replay."""
        return (
            current_item.status == status
            and current_item.last_run_id == run_id
            and (branch_name is None or current_item.branch_name == branch_name)
            and (merge_request_url is None or current_item.merge_request_url == merge_request_url)
            and (merge_request_iid is None or current_item.merge_request_iid == merge_request_iid)
            and (commit_sha is None or current_item.commit_sha == commit_sha)
            and (log_excerpt is None or current_item.log_excerpt == log_excerpt)
        )

    def _require_item(self, document: DashboardDocument, dashboard_item_id: str) -> DashboardItem:
        """Return one existing dashboard item or raise."""
        item = document.items_by_id().get(dashboard_item_id)
        if item is None:
            raise ValueError(f"Dashboard item not found: {dashboard_item_id}")
        return item
