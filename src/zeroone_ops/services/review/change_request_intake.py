"""Change-request intake service."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass

from zeroone_ops.models.review import ChangeRequestReviewCandidate
from zeroone_ops.models.state import AppState
from zeroone_ops.providers.gitlab_review_client import GitLabReviewClient
from zeroone_ops.providers.review_platform import (
    ChangeRequestReviewFetchClientProtocol,
)
from zeroone_ops.services.review.change_request_selector import ChangeRequestSelector
from zeroone_ops.settings import (
    SettingsError,
    load_current_change_request_number,
    load_gitlab_connection_config,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeRequestIntakeResult:
    """Capture the result of selecting a change request for review."""

    selected_change_request: ChangeRequestReviewCandidate | None
    change_request_count: int
    message: str
    selected_skip_reason: str | None = None


class ChangeRequestIntakeService:
    """Fetch and select one provider-backed change request for review."""

    def __init__(
        self,
        review_client: ChangeRequestReviewFetchClientProtocol | None = None,
        selector: ChangeRequestSelector | None = None,
    ) -> None:
        """Initialize the change-request intake service."""
        self.review_client = review_client
        self.selector = selector or ChangeRequestSelector()

    def select_change_request(self, *, state: AppState) -> ChangeRequestIntakeResult:
        """Fetch one change request from CI context and select it for review."""
        try:
            gitlab_config = load_gitlab_connection_config()
        except SettingsError:
            return ChangeRequestIntakeResult(
                selected_change_request=None,
                change_request_count=0,
                message="No change request selected. Review platform credentials not configured.",
                selected_skip_reason=None,
            )
        try:
            change_request_number = load_current_change_request_number()
        except SettingsError:
            return ChangeRequestIntakeResult(
                selected_change_request=None,
                change_request_count=0,
                message="No change request selected. CI change request number is invalid.",
                selected_skip_reason=None,
            )
        if change_request_number is None:
            return ChangeRequestIntakeResult(
                selected_change_request=None,
                change_request_count=0,
                message=(
                    "No change request selected. Review runs are only supported for "
                    "CI-triggered change requests."
                ),
                selected_skip_reason=None,
            )

        review_client = self.review_client or GitLabReviewClient(gitlab_config)
        LOGGER.info(
            "review intake targeting change request from CI context",
            extra={"change_request_number": change_request_number},
        )
        change_requests = [
            review_client.get_change_request(
                project_id=gitlab_config.project_id,
                change_request_number=change_request_number,
            )
        ]
        change_request_count = len(change_requests)
        if not change_requests:
            return ChangeRequestIntakeResult(
                selected_change_request=None,
                change_request_count=0,
                message="No reviewable change request found in the configured repository.",
                selected_skip_reason=None,
            )
        selected_change_request = self.selector.select(change_requests, state)
        if selected_change_request is None:
            skip_reason_counts = Counter[str]()
            for change_request in change_requests:
                reason = self.selector.skip_reason(change_request, state)
                if reason is not None:
                    skip_reason_counts[reason] += 1
                    LOGGER.info(
                        "skipped change request during intake",
                        extra={
                            "change_request_number": change_request.change_request_number,
                            "head_sha": change_request.head_sha,
                            "reason": reason,
                        },
                    )
            if skip_reason_counts.get("already_reviewed_revision", 0) == change_request_count:
                selected_change_request = change_requests[0]
                return ChangeRequestIntakeResult(
                    selected_change_request=selected_change_request,
                    change_request_count=change_request_count,
                    message="",
                    selected_skip_reason="already_reviewed_revision",
                )
            return ChangeRequestIntakeResult(
                selected_change_request=None,
                change_request_count=change_request_count,
                message=self._build_no_change_request_message(
                    change_request_count=change_request_count,
                    skip_reason_counts=skip_reason_counts,
                ),
                selected_skip_reason=None,
            )
        LOGGER.info(
            "selected change request for review",
            extra={
                "change_request_number": selected_change_request.change_request_number,
                "head_sha": selected_change_request.head_sha,
                "source_branch": selected_change_request.source_branch,
                "target_branch": selected_change_request.target_branch,
            },
        )
        return ChangeRequestIntakeResult(
            selected_change_request=selected_change_request,
            change_request_count=change_request_count,
            message="",
            selected_skip_reason=None,
        )

    def _build_no_change_request_message(
        self,
        *,
        change_request_count: int,
        skip_reason_counts: Counter[str],
    ) -> str:
        """Build a no-work summary for review intake."""
        if skip_reason_counts.get("already_reviewed_revision", 0) == change_request_count:
            return (
                "No reviewable change request found. "
                "All open change requests were already reviewed for their current head SHA."
            )
        return "No reviewable change request found in the configured repository."
