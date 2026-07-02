"""Change-request publication service.

This module wraps change-request publication through the GitLab provider.
"""

from __future__ import annotations

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.providers.gitlab_client import GitLabClient


class ChangeRequestService:
    """Create provider-backed change requests through the GitLab client.

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
        assignee_id: int | None = None,
    ) -> ChangeRequestInfo:
        """Create a change request.

        Args:
            project_id: GitLab project identifier.
            source_branch: Source branch name.
            target_branch: Target branch name.
            title: Change-request title.
            description: Change-request description.
            labels: Labels to attach to the change request.
            assignee_id: Optional assignee id to attach to the change request.

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
            assignee_id=assignee_id,
        )

    def find_open(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequestInfo | None:
        """Find an existing open change request."""
        return self.gitlab_client.find_open_merge_request(
            project_id=project_id,
            source_branch=source_branch,
            target_branch=target_branch,
        )

    def assign(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        assignee_id: int,
    ) -> None:
        """Assign an existing change request."""
        self.gitlab_client.update_merge_request_assignee(
            project_id=project_id,
            merge_request_iid=merge_request_iid,
            assignee_id=assignee_id,
        )


MergeRequestService = ChangeRequestService
