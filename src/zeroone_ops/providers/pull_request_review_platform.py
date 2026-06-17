"""Provider-neutral review transport seams for pull-request workflows."""

from __future__ import annotations

from typing import Protocol

from zeroone_ops.models.review import (
    PullRequestReviewCandidate,
    PullRequestReviewNote,
)


class PullRequestReviewFetchClientProtocol(Protocol):
    """Fetch pull-request review candidates and detailed review payloads."""

    def get_pull_request(
        self,
        *,
        project_id: str,
        pull_request_number: int,
    ) -> PullRequestReviewCandidate:
        """Fetch one pull request with change metadata."""


class PullRequestReviewNotesClientProtocol(Protocol):
    """Load provider-backed pull-request notes/comments for continuity."""

    def list_pull_request_notes(
        self,
        *,
        project_id: str,
        pull_request_number: int,
    ) -> list[PullRequestReviewNote]:
        """List provider-backed notes/comments for one pull request."""

    def get_current_user_username(self) -> str:
        """Return the username associated with the active review token."""


class PullRequestReviewPublishClientProtocol(Protocol):
    """Publish provider-backed review output for one pull request."""

    def create_pull_request_note(
        self,
        *,
        project_id: str,
        pull_request_number: int,
        body: str,
    ) -> PullRequestReviewNote:
        """Publish one authoritative review note/comment."""

    def update_pull_request_note(
        self,
        *,
        project_id: str,
        pull_request_number: int,
        note_id: int,
        body: str,
    ) -> PullRequestReviewNote:
        """Update one authoritative review note/comment."""

    def create_pull_request_inline_comment(
        self,
        *,
        project_id: str,
        pull_request_number: int,
        body: str,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        old_path: str,
        new_path: str,
        new_line: int,
    ) -> PullRequestReviewNote:
        """Publish one inline review comment for one pull request."""


class PullRequestReviewPlatformProtocol(
    PullRequestReviewFetchClientProtocol,
    PullRequestReviewNotesClientProtocol,
    PullRequestReviewPublishClientProtocol,
    Protocol,
):
    """Aggregate review protocol for the current Phase 1 runner boundary."""
