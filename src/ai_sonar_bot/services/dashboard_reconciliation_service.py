"""Dashboard reconciliation decision service."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from ai_sonar_bot.models.dashboard import DashboardItem
from ai_sonar_bot.models.gitlab import GitLabMergeRequestState
from ai_sonar_bot.providers.gitlab_client import GitLabClientError
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient


@dataclass(frozen=True)
class DashboardReconciliationDecision:
    """Describe the reconciliation action for one dashboard item."""

    action: str
    message: str
    merge_request_state: GitLabMergeRequestState | None = None


class DashboardReconciliationService:
    """Resolve reconciliation actions from dashboard and merge request state."""

    def __init__(self, review_client: GitLabReviewClient) -> None:
        """Initialize the reconciliation service."""
        self.review_client = review_client

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
            )
        if merge_request.state == "opened":
            return DashboardReconciliationDecision(
                action="noop",
                message=f"Merge request !{merge_request.iid} is still open.",
                merge_request_state=merge_request,
            )
        if merge_request.state == "merged":
            return DashboardReconciliationDecision(
                action="done",
                message=f"Merge request !{merge_request.iid} was merged.",
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
                    merge_request_state=merge_request,
                )
            if item.source == "sonarqube" and item.upstream_active is False:
                return DashboardReconciliationDecision(
                    action="done",
                    message=(
                        f"Merge request !{merge_request.iid} was closed without merge, "
                        "and the dashboard shows the Sonar issue is no longer active."
                    ),
                    merge_request_state=merge_request,
                )
            return DashboardReconciliationDecision(
                action="open",
                message=(
                    f"Merge request !{merge_request.iid} was closed without merge. "
                    "Reopening dashboard item."
                ),
                merge_request_state=merge_request,
            )
        return DashboardReconciliationDecision(
            action="failed",
            message=(
                f"Merge request !{merge_request.iid} returned unsupported state "
                f"`{merge_request.state}`."
            ),
            merge_request_state=merge_request,
        )


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
