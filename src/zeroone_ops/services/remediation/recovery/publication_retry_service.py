"""Retry only verified branch publication without rerunning remediation execution."""

from __future__ import annotations

from dataclasses import dataclass

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.work_item import PublicationRetryState
from zeroone_ops.services.remediation.change_request_publisher import (
    ChangeRequestPublishRequest,
    RemediationChangeRequestPublisher,
)
from zeroone_ops.services.shared.branch_revision_lookup import BranchRevisionLookup


@dataclass(frozen=True)
class PublicationRetryResult:
    """Summarize one bounded change-request publication retry."""

    change_request: ChangeRequestInfo | None = None
    action: str | None = None
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether a change request was created or reused."""
        return self.change_request is not None


class PublicationRetryService:
    """Publish a recorded branch only after verifying its exact remote revision."""

    def __init__(
        self,
        *,
        branch_revision_lookup: BranchRevisionLookup,
        change_request_publisher: RemediationChangeRequestPublisher,
    ) -> None:
        """Initialize the publication retry service."""
        self.branch_revision_lookup = branch_revision_lookup
        self.change_request_publisher = change_request_publisher

    def retry(
        self,
        *,
        publication_retry: PublicationRetryState,
        request: ChangeRequestPublishRequest,
    ) -> PublicationRetryResult:
        """Create or reuse a change request for the verified recorded branch only."""
        if request.source_branch != publication_retry.branch_name:
            return PublicationRetryResult(
                error_message="Publication retry source branch did not match the recorded branch."
            )
        actual_sha = self.branch_revision_lookup.get_branch_head_sha(
            branch_name=publication_retry.branch_name
        )
        if actual_sha is None:
            return PublicationRetryResult(
                error_message="Recorded remediation branch no longer exists remotely."
            )
        if actual_sha != publication_retry.commit_sha:
            return PublicationRetryResult(
                error_message="Recorded remediation branch no longer matches its published commit."
            )
        try:
            published = self.change_request_publisher.publish(request)
        except RuntimeError as error:
            return PublicationRetryResult(
                error_message=f"Recorded branch publication retry failed: {error}"
            )
        return PublicationRetryResult(
            change_request=published.info,
            action=published.action,
        )
