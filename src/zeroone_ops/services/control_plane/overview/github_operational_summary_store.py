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

    def find_open_issue(
        self,
        *,
        repository_id: str | None = None,
        scope_id: str | None = None,
    ) -> GitHubIssueInfo | None:
        """Return the open derived summary issue when present."""
        repository_id = _resolve_scope_id(repository_id=repository_id, scope_id=scope_id)
        return self.client.find_open_issue(
            repository_id=repository_id,
            title=self.TITLE,
            labels=self.LABELS,
        )

    def create_issue(
        self,
        *,
        repository_id: str | None = None,
        scope_id: str | None = None,
        body: str,
    ) -> GitHubIssueInfo:
        """Create the derived summary issue."""
        repository_id = _resolve_scope_id(repository_id=repository_id, scope_id=scope_id)
        return self.client.create_issue(
            repository_id=repository_id,
            title=self.TITLE,
            body=body,
            labels=self.LABELS,
        )

    def update_issue_body(
        self,
        *,
        repository_id: str | None = None,
        scope_id: str | None = None,
        issue_number: int | None = None,
        issue: GitHubIssueInfo | None = None,
        body: str,
    ) -> GitHubIssueInfo:
        """Persist one derived summary-body update."""
        repository_id = _resolve_scope_id(repository_id=repository_id, scope_id=scope_id)
        if issue_number is None:
            if issue is None:
                raise ValueError("GitHub summary update requires an issue.")
            issue_number = issue.number
        return self.client.update_issue(
            repository_id=repository_id,
            issue_number=issue_number,
            body=body,
        )

    def issue_body(self, issue: GitHubIssueInfo) -> str:
        """Return the provider-specific issue body for shared publication."""
        return issue.body


def _resolve_scope_id(*, repository_id: str | None, scope_id: str | None) -> str:
    """Accept the existing GitHub name while supporting the shared store contract."""
    if repository_id is not None and scope_id is not None and repository_id != scope_id:
        raise ValueError("GitHub summary scope identifiers disagree.")
    resolved = repository_id or scope_id
    if resolved is None:
        raise ValueError("GitHub summary storage requires a repository identifier.")
    return resolved
