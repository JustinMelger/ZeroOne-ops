"""Authorize GitLab issue notes for shared policy replay."""

from __future__ import annotations

import logging
from typing import Protocol

from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.providers.gitlab_client import GitLabClientError

LOGGER = logging.getLogger(__name__)

_MAINTAINER_ACCESS_LEVEL = 40


class GitLabPolicyNotePermissionLookup(Protocol):
    """Load effective GitLab project access for one note author."""

    def get_project_member_access_level(self, *, project_id: str, user_id: int) -> int:
        """Return the effective project access level for one user."""


class GitLabPolicyNoteAuthorizationService:
    """Filter GitLab policy notes to Maintainers and Owners."""

    def __init__(
        self,
        client: GitLabPolicyNotePermissionLookup,
        *,
        minimum_access_level: int = _MAINTAINER_ACCESS_LEVEL,
    ) -> None:
        """Initialize the authorization service."""
        self.client = client
        self.minimum_access_level = minimum_access_level

    def authorized_notes(
        self,
        *,
        project_id: str,
        notes: list[GitLabIssueNote],
    ) -> list[GitLabIssueNote]:
        """Return notes from users allowed to mutate project-wide policy."""
        access_level_by_user_id: dict[int, int | None] = {}
        authorized: list[GitLabIssueNote] = []
        for note in notes:
            author_id = note.author_id
            if author_id is None:
                LOGGER.warning(
                    "Ignoring GitLab policy note without an author identity",
                    extra={"note_id": note.id},
                )
                continue
            access_level = access_level_by_user_id.get(author_id)
            if author_id not in access_level_by_user_id:
                try:
                    access_level = self.client.get_project_member_access_level(
                        project_id=project_id,
                        user_id=author_id,
                    )
                except GitLabClientError:
                    LOGGER.warning(
                        "Unable to authorize GitLab policy note; ignoring it",
                        extra={"note_id": note.id, "author_id": author_id},
                    )
                    access_level = None
                access_level_by_user_id[author_id] = access_level
            if access_level is not None and access_level >= self.minimum_access_level:
                authorized.append(note)
        return authorized
