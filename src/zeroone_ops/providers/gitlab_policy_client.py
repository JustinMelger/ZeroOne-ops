"""GitLab policy-issue transport client."""

from __future__ import annotations

from zeroone_ops.models.config import GitLabConnectionConfig
from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient


class GitLabPolicyClient:
    """Provider-local transport for the one authoritative GitLab policy issue."""

    def __init__(
        self,
        config: GitLabConnectionConfig,
        *,
        issue_client: GitLabWorkItemClient | None = None,
    ) -> None:
        """Initialize the policy transport from GitLab connection settings."""
        self._issue_client = issue_client or GitLabWorkItemClient(config)

    def list_open_issues(
        self,
        *,
        project_id: str,
        labels: list[str],
    ) -> list[GitLabIssueInfo]:
        """List labelled open issues for policy-layer selection."""
        return self._issue_client.list_open_issues(project_id=project_id, labels=labels)

    def create_issue(
        self,
        *,
        project_id: str,
        title: str,
        description: str,
        labels: list[str],
    ) -> GitLabIssueInfo:
        """Create the authoritative GitLab policy issue."""
        return self._issue_client.create_issue(
            project_id=project_id,
            title=title,
            description=description,
            labels=labels,
        )

    def update_issue(
        self,
        *,
        project_id: str,
        issue_iid: int,
        title: str,
        description: str,
        labels: list[str],
    ) -> GitLabIssueInfo:
        """Persist the rendered authoritative policy issue body."""
        return self._issue_client.update_issue(
            project_id=project_id,
            issue_iid=issue_iid,
            title=title,
            description=description,
            labels=labels,
        )

    def list_issue_notes(self, *, project_id: str, issue_iid: int) -> list[GitLabIssueNote]:
        """List every note for one authoritative policy issue."""
        return self._issue_client.list_issue_notes(project_id=project_id, issue_iid=issue_iid)

    def get_project_member_access_level(self, *, project_id: str, user_id: int) -> int:
        """Return one user's effective project access level."""
        return self._issue_client.get_project_member_access_level(
            project_id=project_id,
            user_id=user_id,
        )
