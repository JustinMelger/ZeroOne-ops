"""GitLab API client.

This module will provide GitLab REST integration for merge request creation.
"""

from __future__ import annotations

from ai_sonar_bot.models.gitlab import MergeRequestInfo


class GitLabClient:
    """Placeholder GitLab client for the initial scaffold."""

    def create_merge_request(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str] | None = None,
    ) -> MergeRequestInfo:
        """Create a merge request in GitLab.

        Args:
            project_id: GitLab project identifier.
            source_branch: Source branch name.
            target_branch: Target branch name.
            title: Merge request title.
            description: Merge request description.
            labels: Optional labels to attach.

        Returns:
            Metadata for the created merge request.
        """
        raise NotImplementedError("GitLab integration is not implemented yet.")
