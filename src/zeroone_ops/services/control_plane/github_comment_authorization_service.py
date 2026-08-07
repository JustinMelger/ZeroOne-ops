"""Authorize GitHub issue comments for provider-local control-plane actions."""

from __future__ import annotations

from typing import Protocol

from zeroone_ops.models.github import GitHubIssueComment
from zeroone_ops.providers.github_client import GitHubClientError


class GitHubCommentPermissionLookup(Protocol):
    """Load one user's repository permission through provider-local transport."""

    def get_repository_permission(self, *, repository_id: str, username: str) -> str:
        """Return the GitHub repository permission for one username."""


class GitHubCommentAuthorizationService:
    """Filter GitHub issue comments to users authorized for control-plane actions."""

    def __init__(
        self,
        client: GitHubCommentPermissionLookup,
        *,
        required_repository_permission: str = "admin",
    ) -> None:
        """Initialize the authorization service."""
        self.client = client
        self.required_repository_permission = required_repository_permission

    def authorized_comments(
        self,
        *,
        repository_id: str,
        comments: list[GitHubIssueComment],
    ) -> list[GitHubIssueComment]:
        """Return comments from users allowed to mutate control-plane state."""
        permission_by_username: dict[str, str] = {}
        authorized: list[GitHubIssueComment] = []
        for comment in comments:
            username = comment.author_username
            if not username:
                continue
            permission = permission_by_username.get(username)
            if permission is None:
                try:
                    permission = self.client.get_repository_permission(
                        repository_id=repository_id,
                        username=username,
                    )
                except GitHubClientError:
                    permission = ""
                permission_by_username[username] = permission
            if permission == self.required_repository_permission:
                authorized.append(comment)
        return authorized
