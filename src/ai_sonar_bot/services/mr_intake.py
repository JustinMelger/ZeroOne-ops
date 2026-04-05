"""Merge request intake service."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ai_sonar_bot.models.review import MergeRequestReviewCandidate
from ai_sonar_bot.models.state import AppState
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient
from ai_sonar_bot.services.mr_selector import MergeRequestSelector
from ai_sonar_bot.settings import (
    SettingsError,
    load_current_merge_request_iid,
    load_gitlab_connection_config,
)


@dataclass(frozen=True)
class MergeRequestIntakeResult:
    """Capture the result of selecting a merge request for review."""

    selected_merge_request: MergeRequestReviewCandidate | None
    merge_request_count: int
    message: str


class MergeRequestIntakeService:
    """Fetch and select one open GitLab merge request for review."""

    def __init__(
        self,
        review_client: GitLabReviewClient | None = None,
        selector: MergeRequestSelector | None = None,
    ) -> None:
        """Initialize the merge request intake service."""
        self.review_client = review_client
        self.selector = selector or MergeRequestSelector()

    def select_merge_request(self, *, state: AppState) -> MergeRequestIntakeResult:
        """Fetch open merge requests and select one candidate."""
        try:
            gitlab_config = load_gitlab_connection_config()
            merge_request_iid = load_current_merge_request_iid()
        except SettingsError:
            return MergeRequestIntakeResult(
                selected_merge_request=None,
                merge_request_count=0,
                message="No merge request selected. GitLab credentials not configured.",
            )

        review_client = self.review_client or GitLabReviewClient(gitlab_config)
        if merge_request_iid is not None:
            merge_requests = [
                review_client.get_merge_request(
                    project_id=gitlab_config.project_id,
                    merge_request_iid=merge_request_iid,
                )
            ]
        else:
            merge_requests = review_client.list_open_merge_requests(
                project_id=gitlab_config.project_id
            )
        merge_request_count = len(merge_requests)
        if not merge_requests:
            return MergeRequestIntakeResult(
                selected_merge_request=None,
                merge_request_count=0,
                message="No reviewable GitLab merge request found in the configured project.",
            )
        selected_merge_request = self.selector.select(merge_requests, state)
        if selected_merge_request is None:
            skip_reason_counts = Counter[str]()
            for merge_request in merge_requests:
                reason = self.selector.skip_reason(merge_request, state)
                if reason is not None:
                    skip_reason_counts[reason] += 1
            return MergeRequestIntakeResult(
                selected_merge_request=None,
                merge_request_count=merge_request_count,
                message=self._build_no_merge_request_message(
                    merge_request_count=merge_request_count,
                    skip_reason_counts=skip_reason_counts,
                ),
            )
        return MergeRequestIntakeResult(
            selected_merge_request=selected_merge_request,
            merge_request_count=merge_request_count,
            message="",
        )

    def _build_no_merge_request_message(
        self,
        *,
        merge_request_count: int,
        skip_reason_counts: Counter[str],
    ) -> str:
        """Build a no-work summary for review intake."""
        if skip_reason_counts.get("already_reviewed_revision", 0) == merge_request_count:
            return (
                "No reviewable GitLab merge request found. "
                "All open merge requests were already reviewed for their current head SHA."
            )
        return "No reviewable GitLab merge request found in the configured project."
