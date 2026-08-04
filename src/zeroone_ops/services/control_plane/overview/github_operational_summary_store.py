"""Provider-local transport for the derived GitHub operational summary issue."""

from __future__ import annotations

from typing import Protocol

from zeroone_ops.models.github import GitHubIssueInfo


class GitHubOperationalSummaryIssueClient(Protocol):
    """Provide the narrow GitHub issue transport used by the summary store."""

    def find_open_issue(
        self,
        *,
        repository_id: str,
        title: str,
        labels: list[str] | None = None,
    ) -> GitHubIssueInfo | None:
        """Find one open issue by its title and labels."""
        ...

    def create_issue(
        self,
        *,
        repository_id: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> GitHubIssueInfo:
        """Create one GitHub issue."""
        ...

    def update_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
        body: str,
    ) -> GitHubIssueInfo:
        """Update one GitHub issue body."""
        ...


class GitHubOperationalSummaryStore:
    """Load, create, and update the derived GitHub operational summary issue."""

    TITLE = "ZeroOne Ops Summary"
    LABELS = ["zeroone-summary"]

    def __init__(self, client: GitHubOperationalSummaryIssueClient) -> None:
        """Initialize the provider-local summary issue store."""
        self.client = client

    def find_open_issue(self, *, repository_id: str) -> GitHubIssueInfo | None:
        """Return the open derived summary issue when present."""
        return self.client.find_open_issue(
            repository_id=repository_id,
            title=self.TITLE,
            labels=self.LABELS,
        )

    def create_issue(self, *, repository_id: str, body: str) -> GitHubIssueInfo:
        """Create the derived summary issue."""
        return self.client.create_issue(
            repository_id=repository_id,
            title=self.TITLE,
            body=body,
            labels=self.LABELS,
        )

    def update_issue_body(
        self,
        *,
        repository_id: str,
        issue_number: int,
        body: str,
    ) -> GitHubIssueInfo:
        """Persist one derived summary-body update."""
        return self.client.update_issue(
            repository_id=repository_id,
            issue_number=issue_number,
            body=body,
        )
