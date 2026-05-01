"""Dashboard mirroring for merge-request review results."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.models.review import MergeRequestReviewCandidate, ReviewResult
from zeroone_ops.services.dashboard.dashboard_service import DashboardService

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
        """Update a linked remediation item or fall back to one review-status item."""
        try:
            document = self.dashboard_service.load_or_create(project_id=project_id)
            linked_item = _find_linked_remediation_item(
                document.items_by_id().values(),
                merge_request,
            )
            item = (
                _build_updated_remediation_item(
                    current_item=linked_item,
                    merge_request=merge_request,
                    review_result=review_result,
                )
                if linked_item is not None
                else _build_review_status_item(
                    merge_request=merge_request,
                    review_result=review_result,
                )
            )
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


def _find_linked_remediation_item(
    items: Iterable[DashboardItem],
    merge_request: MergeRequestReviewCandidate,
) -> DashboardItem | None:
    """Return one remediation item linked to the reviewed merge request."""
    for item in items:
        if not isinstance(item, DashboardItem):
            continue
        if item.type == "review_status" or item.source == "pull_request_review":
            continue
        if item.merge_request_iid == merge_request.iid:
            return item
    for item in items:
        if not isinstance(item, DashboardItem):
            continue
        if item.type == "review_status" or item.source == "pull_request_review":
            continue
        if item.merge_request_url == merge_request.web_url:
            return item
    return None


def _build_updated_remediation_item(
    *,
    current_item: DashboardItem,
    merge_request: MergeRequestReviewCandidate,
    review_result: ReviewResult,
) -> DashboardItem:
    """Attach bounded review metadata to a linked remediation item."""
    return current_item.model_copy(
        update={
            "reviewed_head_sha": merge_request.head_sha,
            "review_status": review_result.classification,
            "review_findings_count": len(review_result.findings),
            "review_feedback_summary": review_result.summary,
            "review_follow_up_lines": list(review_result.follow_up_lines),
            "review_feedback_updated_at": datetime.now(UTC),
            "review_confidence": review_result.review_confidence,
            "review_confidence_reason": review_result.review_confidence_reason,
            "commit_sha": merge_request.head_sha,
        }
    )


def _build_review_status_item(
    *,
    merge_request: MergeRequestReviewCandidate,
    review_result: ReviewResult,
) -> DashboardItem:
    """Build a fallback standalone review-status dashboard item."""
    summary = _dashboard_review_display_summary(review_result)
    if review_result.classification == "manual_review_only":
        follow_up_suffix = "".join(
            f"\n{line}" for line in review_result.follow_up_lines if line
        )
        summary = (
            "Bot assessment was insufficient for a trustworthy review decision. "
            f"{review_result.summary}"
            f"{follow_up_suffix}"
        )
    if review_result.review_confidence is not None:
        confidence_summary = f" Review confidence: {review_result.review_confidence:.2f}."
        if review_result.review_confidence_reason:
            confidence_summary = (
                f"{confidence_summary} Reason: {review_result.review_confidence_reason}"
            )
        summary = f"{summary}{confidence_summary}"
    return DashboardItem(
        id=f"mr-review:{merge_request.iid}:{merge_request.head_sha}",
        source="pull_request_review",
        type="review_status",
        status="done",
        title=f"Review status for !{merge_request.iid}",
        summary=summary,
        priority="low",
        source_reference=merge_request.web_url,
        merge_request_iid=merge_request.iid,
        merge_request_url=merge_request.web_url,
        reviewed_head_sha=merge_request.head_sha,
        review_status=review_result.classification,
        review_findings_count=len(review_result.findings),
        review_feedback_summary=review_result.summary,
        review_follow_up_lines=list(review_result.follow_up_lines),
        review_feedback_updated_at=datetime.now(UTC),
        review_confidence=review_result.review_confidence,
        review_confidence_reason=review_result.review_confidence_reason,
        commit_sha=merge_request.head_sha,
    )


def _dashboard_review_display_summary(review_result: ReviewResult) -> str:
    """Build the dashboard-visible review summary from shared final review output."""
    parts = [review_result.summary]
    parts.extend(line for line in review_result.follow_up_lines if line)
    return "\n".join(parts)
