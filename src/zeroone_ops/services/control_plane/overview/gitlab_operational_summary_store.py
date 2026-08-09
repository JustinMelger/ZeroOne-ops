"""Provider-local storage for the derived GitLab operational summary issue."""

from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.providers.gitlab_work_item_client import GitLabWorkItemClient


class GitLabOperationalSummaryStore:
    """Load, create, and update the one derived GitLab summary issue."""

    TITLE = "ZeroOne Ops Summary"
    LABELS = ["zeroone-summary"]

    def __init__(self, client: GitLabWorkItemClient) -> None:
        """Initialize the summary store over the dedicated issue transport."""
        self.client = client

    def find_open_issue(self, *, scope_id: str) -> GitLabIssueInfo | None:
        """Find one summary issue by its authoritative discovery indexes."""
        matches = [
            issue
            for issue in self.client.list_open_issues(project_id=scope_id, labels=self.LABELS)
            if issue.title == self.TITLE
        ]
        if len(matches) > 1:
            raise GitLabClientError(
                "Ambiguous GitLab operational summary match for title "
                f"{self.TITLE!r}: {len(matches)} issues found."
            )
        return matches[0] if matches else None

    def create_issue(self, *, scope_id: str, body: str) -> GitLabIssueInfo:
        """Create the derived summary issue without assigning authoritative state."""
        return self.client.create_issue(
            project_id=scope_id,
            title=self.TITLE,
            description=body,
            labels=self.LABELS,
        )

    def update_issue_body(
        self,
        *,
        scope_id: str,
        issue: GitLabIssueInfo,
        body: str,
    ) -> GitLabIssueInfo:
        """Update only the derived summary body when its view changes."""
        return self.client.update_issue(
            project_id=scope_id,
            issue_iid=issue.iid,
            title=self.TITLE,
            description=body,
            labels=self.LABELS,
        )

    def issue_body(self, issue: GitLabIssueInfo) -> str:
        """Return the provider-specific issue description for shared publication."""
        return issue.description
