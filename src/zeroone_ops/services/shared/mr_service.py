"""Merge request service.

This module wraps merge request creation through the GitLab provider.
"""

from __future__ import annotations

from zeroone_ops.models.gitlab import MergeRequestInfo
from zeroone_ops.providers.gitlab_client import GitLabClient


class MergeRequestService:
    """Create merge requests through the GitLab client.

    Args:
        gitlab_client: GitLab provider implementation.
    """

    def __init__(self, gitlab_client: GitLabClient) -> None:
        """Initialize the merge request service.

        Args:
            gitlab_client: GitLab provider implementation.
        """
        self.gitlab_client = gitlab_client

    def create(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str],
    ) -> MergeRequestInfo:
        """Create a merge request.

        Args:
            project_id: GitLab project identifier.
            source_branch: Source branch name.
            target_branch: Target branch name.
            title: Merge request title.
            description: Merge request description.
            labels: Labels to attach to the merge request.

        Returns:
            Metadata for the created merge request.
        """
        return self.gitlab_client.create_merge_request(
            project_id=project_id,
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
            labels=labels,
        )

    def find_open(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
    ) -> MergeRequestInfo | None:
        """Find an existing open merge request."""
        return self.gitlab_client.find_open_merge_request(
            project_id=project_id,
            source_branch=source_branch,
            target_branch=target_branch,
        )
