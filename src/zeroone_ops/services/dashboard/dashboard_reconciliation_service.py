"""Dashboard reconciliation decision service."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.models.gitlab import GitLabMergeRequestState
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.providers.review.gitlab import GitLabReviewClientProtocol


@dataclass(frozen=True)
class DashboardReconciliationDecision:
    """Describe the reconciliation action for one dashboard item."""

    action: str
    message: str
    retry_eligible: bool | None = None
    retry_block_reason: str | None = None
    merge_request_state: GitLabMergeRequestState | None = None


class DashboardReconciliationService:
    """Resolve reconciliation actions from dashboard and merge request state."""

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
        """Return the reconciliation action for one `mr_opened` item."""
        merge_request_iid = item.merge_request_iid or merge_request_iid_from_url(
            item.merge_request_url
        )
        if merge_request_iid is None:
            return DashboardReconciliationDecision(
                action="failed",
                message=(
                    f"Dashboard item {item.id} cannot be reconciled because its merge "
                    "request IID could not be determined."
                ),
                retry_eligible=False,
                retry_block_reason="Merge request IID is missing.",
            )
        try:
            merge_request = self.review_client.get_merge_request_state(
                project_id=project_id,
                merge_request_iid=merge_request_iid,
            )
        except (GitLabClientError, httpx.HTTPError) as error:
            return DashboardReconciliationDecision(
                action="failed",
                message=(
                    f"Dashboard item {item.id} cannot be reconciled because merge "
                    f"request metadata is inaccessible: {error}"
                ),
                retry_eligible=False,
                retry_block_reason="Merge request metadata is inaccessible.",
            )
        if merge_request.state == "opened":
            return DashboardReconciliationDecision(
                action="noop",
                message=f"Merge request !{merge_request.iid} is still open.",
                retry_eligible=item.retry_eligible,
                retry_block_reason=item.retry_block_reason,
                merge_request_state=merge_request,
            )
        if merge_request.state == "merged":
            return DashboardReconciliationDecision(
                action="done",
                message=f"Merge request !{merge_request.iid} was merged.",
                retry_eligible=False,
                retry_block_reason=None,
                merge_request_state=merge_request,
            )
        if merge_request.state == "closed":
            if (
                item.branch_name != merge_request.source_branch
                or item.commit_sha != merge_request.head_sha
            ):
                return DashboardReconciliationDecision(
                    action="failed",
                    message=(
                        f"Merge request !{merge_request.iid} was closed, but stored "
                        "branch or commit traceability no longer matches."
                    ),
                    retry_eligible=False,
                    retry_block_reason="Stored branch or commit traceability no longer matches.",
                    merge_request_state=merge_request,
                )
            if item.source == "sonarqube" and item.upstream_active is False:
                return DashboardReconciliationDecision(
                    action="done",
                    message=(
                        f"Merge request !{merge_request.iid} was closed without merge, "
                        "and the dashboard shows the Sonar issue is no longer active."
                    ),
                    retry_eligible=False,
                    retry_block_reason=None,
                    merge_request_state=merge_request,
                )
            retry_eligible, retry_block_reason = self._retry_state_for_closed_item(item)
            if retry_eligible:
                return DashboardReconciliationDecision(
                    action="open",
                    message=(
                        f"Merge request !{merge_request.iid} was closed without merge. "
                        "Reopening dashboard item with review-guided retry eligibility."
                    ),
                    retry_eligible=True,
                    retry_block_reason=None,
                    merge_request_state=merge_request,
                )
            if retry_block_reason == "No linked review outcome available.":
                return DashboardReconciliationDecision(
                    action="open",
                    message=(
                        f"Merge request !{merge_request.iid} was closed without merge. "
                        "Reopening dashboard item."
                    ),
                    retry_eligible=False,
                    retry_block_reason=retry_block_reason,
                    merge_request_state=merge_request,
                )
            return DashboardReconciliationDecision(
                action="failed",
                message=(
                    f"Merge request !{merge_request.iid} was closed without merge, "
                    f"but retry is blocked: {retry_block_reason}"
                ),
                retry_eligible=False,
                retry_block_reason=retry_block_reason,
                merge_request_state=merge_request,
            )
        return DashboardReconciliationDecision(
            action="failed",
            message=(
                f"Merge request !{merge_request.iid} returned unsupported state "
                f"`{merge_request.state}`."
            ),
            retry_eligible=False,
            retry_block_reason=f"Unsupported merge request state: {merge_request.state}.",
            merge_request_state=merge_request,
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


def merge_request_iid_from_url(url: str | None) -> int | None:
    """Extract a merge request IID from a GitLab merge request URL."""
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
