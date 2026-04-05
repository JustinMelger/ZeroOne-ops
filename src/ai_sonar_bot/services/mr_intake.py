"""Merge request intake service."""

from __future__ import annotations

from dataclasses import dataclass

from ai_sonar_bot.models.review import MergeRequestReviewCandidate
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient
from ai_sonar_bot.settings import SettingsError, load_gitlab_connection_config


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
    ) -> None:
        """Initialize the merge request intake service."""
        self.review_client = review_client

    def select_merge_request(self) -> MergeRequestIntakeResult:
        """Fetch open merge requests and select one candidate."""
        try:
            gitlab_config = load_gitlab_connection_config()
        except SettingsError:
            return MergeRequestIntakeResult(
                selected_merge_request=None,
                merge_request_count=0,
                message="No merge request selected. GitLab credentials not configured.",
            )

        review_client = self.review_client or GitLabReviewClient(gitlab_config)
        merge_requests = review_client.list_open_merge_requests(project_id=gitlab_config.project_id)
        merge_request_count = len(merge_requests)
        if not merge_requests:
            return MergeRequestIntakeResult(
                selected_merge_request=None,
                merge_request_count=0,
                message="No reviewable GitLab merge request found in the configured project.",
            )
        return MergeRequestIntakeResult(
            selected_merge_request=merge_requests[0],
            merge_request_count=merge_request_count,
            message="",
        )
