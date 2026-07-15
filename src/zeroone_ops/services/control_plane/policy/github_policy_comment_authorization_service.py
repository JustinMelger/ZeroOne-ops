"""Authorize GitHub policy comments for shared policy replay."""

from __future__ import annotations

from zeroone_ops.models.github import GitHubIssueComment
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.github_policy_client import GitHubPolicyClient


class GitHubPolicyCommentAuthorizationService:
    """Filter GitHub issue comments to users allowed to mutate repository policy."""

    def __init__(
        self,
        client: GitHubPolicyClient,
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
        """Return comments from users authorized to mutate repository-wide policy."""
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
