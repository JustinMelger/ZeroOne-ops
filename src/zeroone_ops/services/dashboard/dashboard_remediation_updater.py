"""Dashboard lifecycle updates for remediation runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from zeroone_ops.models.dashboard import DashboardDocument, DashboardItem
from zeroone_ops.models.work_item import PublicationRetryState
from zeroone_ops.services.dashboard.dashboard_service import DashboardService


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
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ) -> DashboardRemediationUpdateResult:
        """Mark one dashboard item in progress."""
        return self._update_item(
            project_id=project_id,
            dashboard_item_id=dashboard_item_id,
            status="in_progress",
            run_id=run_id,
            retry_count=retry_count,
            retry_eligible=retry_eligible,
            retry_block_reason=retry_block_reason,
        )

    def mark_change_request_opened(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        branch_name: str,
        change_request_url: str | None = None,
        commit_sha: str,
        change_request_number: int | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
        clear_publication_retry: bool = False,
    ) -> DashboardRemediationUpdateResult:
        """Mark one dashboard item as having an open change request."""
        if change_request_url is None:
            return DashboardRemediationUpdateResult(
                error_message=(
                    "Dashboard remediation update failed: change request URL is required."
                ),
            )
        return self._update_item(
            project_id=project_id,
            dashboard_item_id=dashboard_item_id,
            status="change_request_opened",
            run_id=run_id,
            branch_name=branch_name,
            change_request_url=change_request_url,
            change_request_number=change_request_number,
            commit_sha=commit_sha,
            retry_count=retry_count,
            retry_eligible=retry_eligible,
            retry_block_reason=retry_block_reason,
            clear_publication_retry=clear_publication_retry,
        )

    def mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
        publication_retry: PublicationRetryState | None = None,
    ) -> DashboardRemediationUpdateResult:
        """Mark one dashboard item as failed."""
        return self._update_item(
            project_id=project_id,
            dashboard_item_id=dashboard_item_id,
            status="failed",
            run_id=run_id,
            log_excerpt=error_message,
            retry_count=retry_count,
            retry_eligible=retry_eligible,
            retry_block_reason=retry_block_reason,
            publication_retry=publication_retry,
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
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ) -> DashboardRemediationUpdateResult:
        """Mark one dashboard item done."""
        return self._update_item(
            project_id=project_id,
            dashboard_item_id=dashboard_item_id,
            status="done",
            run_id=run_id,
            log_excerpt=summary,
            retry_count=retry_count,
            retry_eligible=retry_eligible,
            retry_block_reason=retry_block_reason,
        )

    def mark_open(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        summary: str | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ) -> DashboardRemediationUpdateResult:
        """Reopen one dashboard item."""
        return self._update_item(
            project_id=project_id,
            dashboard_item_id=dashboard_item_id,
            status="open",
            run_id=run_id,
            log_excerpt=summary,
            clear_change_request_traceability=True,
            retry_count=retry_count,
            retry_eligible=retry_eligible,
            retry_block_reason=retry_block_reason,
        )

    def _update_item(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        status: str,
        run_id: str,
        branch_name: str | None = None,
        change_request_url: str | None = None,
        change_request_number: int | None = None,
        commit_sha: str | None = None,
        log_excerpt: str | None = None,
        clear_change_request_traceability: bool = False,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
        publication_retry: PublicationRetryState | None = None,
        clear_publication_retry: bool = False,
    ) -> DashboardRemediationUpdateResult:
        """Load, update, and persist one dashboard item."""
        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                document = self.dashboard_service.load_or_create(project_id=project_id)
                current_item = self._require_item(document, dashboard_item_id)
                if self._is_idempotent_update(
                    current_item=current_item,
                    status=status,
                    run_id=run_id,
                    branch_name=branch_name,
                    change_request_url=change_request_url,
                    change_request_number=change_request_number,
                    commit_sha=commit_sha,
                    log_excerpt=log_excerpt,
                    clear_change_request_traceability=clear_change_request_traceability,
                    retry_count=retry_count,
                    retry_eligible=retry_eligible,
                    retry_block_reason=retry_block_reason,
                    publication_retry=publication_retry,
                    clear_publication_retry=clear_publication_retry,
                ):
                    return DashboardRemediationUpdateResult(
                        dashboard_issue_url=document.issue_url,
                        updated_item=current_item,
                    )
                updated_item = self._build_updated_item(
                    current_item=current_item,
                    status=status,
                    run_id=run_id,
                    branch_name=branch_name,
                    change_request_url=change_request_url,
                    change_request_number=change_request_number,
                    commit_sha=commit_sha,
                    log_excerpt=log_excerpt,
                    clear_change_request_traceability=clear_change_request_traceability,
                    retry_count=retry_count,
                    retry_eligible=retry_eligible,
                    retry_block_reason=retry_block_reason,
                    publication_retry=publication_retry,
                    clear_publication_retry=clear_publication_retry,
                )
                updated_document = self.dashboard_service.upsert_items(
                    project_id=project_id,
                    items=[updated_item],
                )
            except Exception as error:  # pragma: no cover - defensive orchestration guard
                last_error = error
                continue
            persisted_item = updated_document.items_by_id().get(dashboard_item_id, updated_item)
            return DashboardRemediationUpdateResult(
                dashboard_issue_url=updated_document.issue_url,
                updated_item=persisted_item,
            )
        return DashboardRemediationUpdateResult(
            error_message=f"Dashboard remediation update failed: {last_error}",
        )

    def _build_updated_item(
        self,
        *,
        current_item: DashboardItem,
        status: str,
        run_id: str,
        branch_name: str | None,
        change_request_url: str | None,
        change_request_number: int | None,
        commit_sha: str | None,
        log_excerpt: str | None,
        clear_change_request_traceability: bool,
        retry_count: int | None,
        retry_eligible: bool | None,
        retry_block_reason: str | None,
        publication_retry: PublicationRetryState | None,
        clear_publication_retry: bool,
    ) -> DashboardItem:
        """Return one lifecycle-updated dashboard item."""
        return current_item.model_copy(
            update={
                "status": status,
                "last_run_id": run_id,
                "status_updated_at": datetime.now(UTC),
                "branch_name": branch_name if branch_name is not None else current_item.branch_name,
                "change_request_url": (
                    None
                    if clear_change_request_traceability
                    else (
                        change_request_url
                        if change_request_url is not None
                        else current_item.change_request_url
                    )
                ),
                "change_request_number": (
                    None
                    if clear_change_request_traceability
                    else (
                        change_request_number
                        if change_request_number is not None
                        else current_item.change_request_number
                    )
                ),
                "commit_sha": commit_sha if commit_sha is not None else current_item.commit_sha,
                "log_excerpt": log_excerpt if log_excerpt is not None else current_item.log_excerpt,
                "retry_count": retry_count if retry_count is not None else current_item.retry_count,
                "retry_eligible": (
                    retry_eligible if retry_eligible is not None else current_item.retry_eligible
                ),
                "retry_block_reason": (
                    None
                    if retry_eligible is not None and retry_block_reason is None
                    else (
                        retry_block_reason
                        if retry_block_reason is not None
                        else current_item.retry_block_reason
                    )
                ),
                "publication_retry": (
                    None
                    if clear_publication_retry
                    else (
                        publication_retry
                        if publication_retry is not None
                        else current_item.publication_retry
                    )
                ),
            }
        )

    def _is_idempotent_update(
        self,
        *,
        current_item: DashboardItem,
        status: str,
        run_id: str,
        branch_name: str | None,
        change_request_url: str | None,
        change_request_number: int | None,
        commit_sha: str | None,
        log_excerpt: str | None,
        clear_change_request_traceability: bool,
        retry_count: int | None,
        retry_eligible: bool | None,
        retry_block_reason: str | None,
        publication_retry: PublicationRetryState | None,
        clear_publication_retry: bool,
    ) -> bool:
        """Return whether one lifecycle update would be a no-op replay."""
        return (
            current_item.status == status
            and current_item.last_run_id == run_id
            and (branch_name is None or current_item.branch_name == branch_name)
            and (
                change_request_url is None or current_item.change_request_url == change_request_url
            )
            and (
                change_request_number is None
                or current_item.change_request_number == change_request_number
            )
            and (commit_sha is None or current_item.commit_sha == commit_sha)
            and (log_excerpt is None or current_item.log_excerpt == log_excerpt)
            and (retry_count is None or current_item.retry_count == retry_count)
            and (retry_eligible is None or current_item.retry_eligible == retry_eligible)
            and (
                (
                    retry_eligible is not None
                    and retry_block_reason is None
                    and current_item.retry_block_reason is None
                )
                or retry_block_reason is None
                or current_item.retry_block_reason == retry_block_reason
            )
            and (
                not clear_change_request_traceability
                or (
                    current_item.change_request_url is None
                    and current_item.change_request_number is None
                )
            )
            and (not clear_publication_retry or current_item.publication_retry is None)
            and (publication_retry is None or current_item.publication_retry == publication_retry)
        )

    def _require_item(self, document: DashboardDocument, dashboard_item_id: str) -> DashboardItem:
        """Return one existing dashboard item or raise."""
        item = document.items_by_id().get(dashboard_item_id)
        if item is None:
            raise ValueError(f"Dashboard item not found: {dashboard_item_id}")
        return item
