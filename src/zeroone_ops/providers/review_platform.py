"""Provider-neutral review transport seams for change-request workflows."""

from __future__ import annotations

from typing import Protocol

from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    ReviewComment,
)


class ReviewPlatformClientError(RuntimeError):
    """Provider-neutral error raised by review platform client seams."""


class ChangeRequestReviewFetchClientProtocol(Protocol):
    """Fetch change-request review candidates and detailed review payloads."""

    def get_change_request(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> ChangeRequestReviewCandidate:
        """Fetch one change request with change metadata."""


class ChangeRequestReviewCommentsClientProtocol(Protocol):
    """Load provider-backed review comments for continuity."""

    def list_change_request_comments(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> list[ReviewComment]:
        """List provider-backed review comments for one change request."""

    def get_current_user_username(self) -> str:
        """Return the username associated with the active review token."""


class ChangeRequestReviewPublishClientProtocol(Protocol):
    """Publish provider-backed review output for one change request."""

    def create_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
    ) -> ReviewComment:
        """Publish one authoritative review comment."""

    def update_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        note_id: int,
        body: str,
    ) -> ReviewComment:
        """Update one authoritative review comment."""

    def create_change_request_inline_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        old_path: str,
        new_path: str,
        new_line: int,
    ) -> ReviewComment:
        """Publish one inline review comment for one change request."""


class ChangeRequestReviewPlatformProtocol(
    ChangeRequestReviewFetchClientProtocol,
    ChangeRequestReviewCommentsClientProtocol,
    ChangeRequestReviewPublishClientProtocol,
    Protocol,
):
    """Aggregate review protocol for the current Phase 1 runner boundary."""
