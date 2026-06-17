"""Merge request intake service."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass

from zeroone_ops.models.review import PullRequestReviewCandidate
from zeroone_ops.models.state import AppState
from zeroone_ops.providers.gitlab_review_client import GitLabReviewClient
from zeroone_ops.providers.pull_request_review_platform import (
    PullRequestReviewFetchClientProtocol,
)
from zeroone_ops.services.review.mr_selector import MergeRequestSelector
from zeroone_ops.settings import (
    SettingsError,
    load_current_merge_request_iid,
    load_gitlab_connection_config,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PullRequestIntakeResult:
    """Capture the result of selecting a pull request for review."""

    selected_pull_request: PullRequestReviewCandidate | None
    pull_request_count: int
    message: str
    selected_skip_reason: str | None = None

    @property
    def selected_merge_request(self) -> PullRequestReviewCandidate | None:
        """Back-compat alias during Phase 1 provider-neutral renaming."""
        return self.selected_pull_request

    @property
    def merge_request_count(self) -> int:
        """Back-compat alias during Phase 1 provider-neutral renaming."""
        return self.pull_request_count


class PullRequestIntakeService:
    """Fetch and select one provider-backed pull request for review."""

    def __init__(
        self,
        review_client: PullRequestReviewFetchClientProtocol | None = None,
        selector: MergeRequestSelector | None = None,
    ) -> None:
        """Initialize the merge request intake service."""
        self.review_client = review_client
        self.selector = selector or MergeRequestSelector()

    def select_pull_request(self, *, state: AppState) -> PullRequestIntakeResult:
        """Fetch one pull request from CI context and select it for review."""
        return self.select_merge_request(state=state)

    def select_merge_request(self, *, state: AppState) -> PullRequestIntakeResult:
        """Back-compat entrypoint during Phase 1 provider-neutral renaming."""
        return self._select_pull_request_impl(state=state)

    def _select_pull_request_impl(self, *, state: AppState) -> PullRequestIntakeResult:
        """Fetch one pull request from CI context and select it for review."""
        try:
            gitlab_config = load_gitlab_connection_config()
        except SettingsError:
            return PullRequestIntakeResult(
                selected_pull_request=None,
                pull_request_count=0,
                message="No merge request selected. GitLab credentials not configured.",
                selected_skip_reason=None,
            )
        try:
            merge_request_iid = load_current_merge_request_iid()
        except SettingsError:
            return PullRequestIntakeResult(
                selected_pull_request=None,
                pull_request_count=0,
                message="No merge request selected. CI merge request IID is invalid.",
                selected_skip_reason=None,
            )
        if merge_request_iid is None:
            return PullRequestIntakeResult(
                selected_pull_request=None,
                pull_request_count=0,
                message=(
                    "No merge request selected. Review runs are only supported for "
                    "CI-triggered merge requests."
                ),
                selected_skip_reason=None,
            )

        review_client = self.review_client or GitLabReviewClient(gitlab_config)
        LOGGER.info(
            "review intake targeting merge request from CI context",
            extra={"mr_iid": merge_request_iid},
        )
        pull_requests = [
            review_client.get_pull_request(
                project_id=gitlab_config.project_id,
                pull_request_number=merge_request_iid,
            )
        ]
        pull_request_count = len(pull_requests)
        if not pull_requests:
            return PullRequestIntakeResult(
                selected_pull_request=None,
                pull_request_count=0,
                message="No reviewable GitLab merge request found in the configured project.",
                selected_skip_reason=None,
            )
        selected_pull_request = self.selector.select(pull_requests, state)
        if selected_pull_request is None:
            skip_reason_counts = Counter[str]()
            for pull_request in pull_requests:
                reason = self.selector.skip_reason(pull_request, state)
                if reason is not None:
                    skip_reason_counts[reason] += 1
                    LOGGER.info(
                        "skipped merge request during intake",
                        extra={
                            "mr_iid": pull_request.iid,
                            "head_sha": pull_request.head_sha,
                            "reason": reason,
                        },
                    )
            if skip_reason_counts.get("already_reviewed_revision", 0) == pull_request_count:
                selected_pull_request = pull_requests[0]
                return PullRequestIntakeResult(
                    selected_pull_request=selected_pull_request,
                    pull_request_count=pull_request_count,
                    message="",
                    selected_skip_reason="already_reviewed_revision",
                )
            return PullRequestIntakeResult(
                selected_pull_request=None,
                pull_request_count=pull_request_count,
                message=self._build_no_merge_request_message(
                    merge_request_count=pull_request_count,
                    skip_reason_counts=skip_reason_counts,
                ),
                selected_skip_reason=None,
            )
        LOGGER.info(
            "selected merge request for review",
            extra={
                "mr_iid": selected_pull_request.iid,
                "head_sha": selected_pull_request.head_sha,
                "source_branch": selected_pull_request.source_branch,
                "target_branch": selected_pull_request.target_branch,
            },
        )
        return PullRequestIntakeResult(
            selected_pull_request=selected_pull_request,
            pull_request_count=pull_request_count,
            message="",
            selected_skip_reason=None,
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


MergeRequestIntakeService = PullRequestIntakeService
