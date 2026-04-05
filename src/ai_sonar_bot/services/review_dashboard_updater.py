"""Dashboard mirroring for merge-request review results."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ai_sonar_bot.models.dashboard import DashboardItem
from ai_sonar_bot.models.review import MergeRequestReviewCandidate, ReviewResult
from ai_sonar_bot.services.dashboard_service import DashboardService

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewDashboardUpdateResult:
    """Capture the result of mirroring review status to the dashboard."""

    dashboard_issue_url: str | None = None
    error_message: str | None = None


class ReviewDashboardUpdater:
    """Mirror completed review runs to the dashboard."""

    def __init__(self, dashboard_service: DashboardService) -> None:
        """Initialize the updater."""
        self.dashboard_service = dashboard_service

    def update(
        self,
        *,
        project_id: str,
        merge_request: MergeRequestReviewCandidate,
        review_result: ReviewResult,
    ) -> ReviewDashboardUpdateResult:
        """Upsert one review-status item into the dashboard."""
        item = DashboardItem(
            id=f"mr-review:{merge_request.iid}:{merge_request.head_sha}",
            source="pull_request_review",
            type="review_status",
            status="done",
            title=f"Review status for !{merge_request.iid}",
            summary=review_result.summary,
            priority="low",
            source_reference=merge_request.web_url,
            merge_request_iid=merge_request.iid,
            merge_request_url=merge_request.web_url,
            reviewed_head_sha=merge_request.head_sha,
            review_status=review_result.classification,
            commit_sha=merge_request.head_sha,
        )
        try:
            document = self.dashboard_service.upsert_items(project_id=project_id, items=[item])
        except Exception as error:  # pragma: no cover - defensive orchestration guard
            LOGGER.warning(
                "review dashboard update failed",
                extra={
                    "mr_iid": merge_request.iid,
                    "head_sha": merge_request.head_sha,
                },
            )
            return ReviewDashboardUpdateResult(
                error_message=f"Dashboard mirror failed: {error}",
            )
        return ReviewDashboardUpdateResult(dashboard_issue_url=document.issue_url)
