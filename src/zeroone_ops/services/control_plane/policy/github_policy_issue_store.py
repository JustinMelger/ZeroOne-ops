"""Provider-local transport for the GitHub policy issue."""

from __future__ import annotations

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.providers.github_policy_client import GitHubPolicyClient


class GitHubPolicyIssueStore:
    """Load, create, and update the authoritative GitHub policy issue."""

    def __init__(
        self,
        client: GitHubPolicyClient,
        *,
        title: str,
        labels: list[str],
    ) -> None:
        """Initialize the provider-local policy issue store."""
        self.client = client
        self.title = title
        self.labels = labels

    def find_open_issue(self, *, repository_id: str) -> GitHubIssueInfo | None:
        """Return the open authoritative policy issue when present."""
        return self.client.find_open_issue(
            repository_id=repository_id,
            title=self.title,
            labels=self.labels,
        )

    def create_issue(
        self,
        *,
        repository_id: str,
        body: str,
    ) -> GitHubIssueInfo:
        """Create the authoritative policy issue."""
        return self.client.create_issue(
            repository_id=repository_id,
            title=self.title,
            body=body,
            labels=self.labels,
        )

    def update_issue_body(
        self,
        *,
        repository_id: str,
        issue_number: int,
        body: str,
    ) -> GitHubIssueInfo:
        """Persist one rendered policy issue body update."""
        return self.client.update_issue(
            repository_id=repository_id,
            issue_number=issue_number,
            body=body,
        )
