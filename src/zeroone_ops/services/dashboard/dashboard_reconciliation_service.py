"""Dashboard reconciliation decision service."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.providers.review.gitlab import GitLabReviewClientProtocol


@dataclass(frozen=True)
class DashboardReconciliationDecision:
    """Describe the reconciliation action for one dashboard item."""

    action: str
    message: str
    retry_eligible: bool | None = None
    retry_block_reason: str | None = None
    change_request_state: ChangeRequestState | None = None


class DashboardReconciliationService:
    """Resolve reconciliation actions from dashboard and change-request state."""

    def __init__(
        self,
        review_client: GitLabReviewClientProtocol,
        *,
        max_review_feedback_retries: int = 1,
    ) -> None:
        """Initialize the reconciliation service."""
        self.review_client = review_client
        self.max_review_feedback_retries = max_review_feedback_retries

    def decide(
        self,
        *,
        project_id: str,
        item: DashboardItem,
    ) -> DashboardReconciliationDecision:
        """Return the reconciliation action for one open change-request item."""
        change_request_number = item.change_request_number or change_request_number_from_url(
            item.change_request_url
        )
        if change_request_number is None:
            return DashboardReconciliationDecision(
                action="failed",
                message=(
                    f"Dashboard item {item.id} cannot be reconciled because its change "
                    "request number could not be determined."
                ),
                retry_eligible=False,
                retry_block_reason="Change request number is missing.",
            )
        try:
            change_request = self.review_client.get_change_request_state(
                project_id=project_id,
                change_request_number=change_request_number,
            )
        except (GitLabClientError, httpx.HTTPError) as error:
            return DashboardReconciliationDecision(
                action="failed",
                message=(
                    f"Dashboard item {item.id} cannot be reconciled because change "
                    f"request metadata is inaccessible: {error}"
                ),
                retry_eligible=False,
                retry_block_reason="Change request metadata is inaccessible.",
            )
        if change_request.state == "opened":
            return DashboardReconciliationDecision(
                action="noop",
                message=f"Change request {change_request.iid} is still open.",
                retry_eligible=item.retry_eligible,
                retry_block_reason=item.retry_block_reason,
                change_request_state=change_request,
            )
        if change_request.state == "merged":
            return DashboardReconciliationDecision(
                action="done",
                message=f"Change request {change_request.iid} was merged.",
                retry_eligible=False,
                retry_block_reason=None,
                change_request_state=change_request,
            )
        if change_request.state == "closed":
            if (
                item.branch_name != change_request.source_branch
                or item.commit_sha != change_request.head_sha
            ):
                return DashboardReconciliationDecision(
                    action="failed",
                    message=(
                        f"Change request {change_request.iid} was closed, but stored "
                        "branch or commit traceability no longer matches."
                    ),
                    retry_eligible=False,
                    retry_block_reason="Stored branch or commit traceability no longer matches.",
                    change_request_state=change_request,
                )
            if item.source == "sonarqube" and item.upstream_active is False:
                return DashboardReconciliationDecision(
                    action="done",
                    message=(
                        f"Change request {change_request.iid} was closed without merge, "
                        "and the dashboard shows the Sonar issue is no longer active."
                    ),
                    retry_eligible=False,
                    retry_block_reason=None,
                    change_request_state=change_request,
                )
            retry_eligible, retry_block_reason = self._retry_state_for_closed_item(item)
            if retry_eligible:
                return DashboardReconciliationDecision(
                    action="open",
                    message=(
                        f"Change request {change_request.iid} was closed without merge. "
                        "Reopening dashboard item with review-guided retry eligibility."
                    ),
                    retry_eligible=True,
                    retry_block_reason=None,
                    change_request_state=change_request,
                )
            if retry_block_reason == "No linked review outcome available.":
                return DashboardReconciliationDecision(
                    action="open",
                    message=(
                        f"Change request {change_request.iid} was closed without merge. "
                        "Reopening dashboard item."
                    ),
                    retry_eligible=False,
                    retry_block_reason=retry_block_reason,
                    change_request_state=change_request,
                )
            return DashboardReconciliationDecision(
                action="failed",
                message=(
                    f"Change request {change_request.iid} was closed without merge, "
                    f"but retry is blocked: {retry_block_reason}"
                ),
                retry_eligible=False,
                retry_block_reason=retry_block_reason,
                change_request_state=change_request,
            )
        return DashboardReconciliationDecision(
            action="failed",
            message=(
                f"Change request {change_request.iid} returned unsupported state "
                f"`{change_request.state}`."
            ),
            retry_eligible=False,
            retry_block_reason=f"Unsupported change request state: {change_request.state}.",
            change_request_state=change_request,
        )

    def _retry_state_for_closed_item(self, item: DashboardItem) -> tuple[bool, str]:
        """Return bounded retry eligibility for one closed remediation MR."""
        if item.review_status is None:
            return False, "No linked review outcome available."
        if item.review_status == "manual_review_only":
            return False, "Latest review outcome requires manual review."
        if item.review_status == "no_findings":
            return False, "Latest review reported no actionable findings."
        retry_count = item.retry_count or 0
        if retry_count >= self.max_review_feedback_retries:
            return (
                False,
                (f"Retry limit reached ({retry_count}/{self.max_review_feedback_retries})."),
            )
        return True, ""


def change_request_number_from_url(url: str | None) -> int | None:
    """Extract a change-request number from a GitLab-style change-request URL."""
    if url is None:
        return None
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    try:
        merge_requests_index = path_parts.index("merge_requests")
    except ValueError:
        return None
    iid_index = merge_requests_index + 1
    if iid_index >= len(path_parts):
        return None
    try:
        return int(path_parts[iid_index])
    except ValueError:
        return None
