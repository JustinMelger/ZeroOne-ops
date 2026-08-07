"""Provider-local storage for the GitLab policy issue."""

from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.providers.gitlab_policy_client import GitLabPolicyClient


class GitLabPolicyIssueStore:
    """Load, create, and update the authoritative GitLab policy issue."""

    def __init__(self, client: GitLabPolicyClient, *, title: str, labels: list[str]) -> None:
        """Initialize the provider-local policy issue store."""
        self.client = client
        self.title = title
        self.labels = labels

    def find_open_issue(self, *, project_id: str) -> GitLabIssueInfo | None:
        """Return the open authoritative policy issue, when present."""
        matches = [
            issue
            for issue in self.client.list_open_issues(
                project_id=project_id,
                labels=self.labels,
            )
            if issue.title == self.title
        ]
        if len(matches) > 1:
            raise GitLabClientError(
                "Ambiguous GitLab policy issue match for title "
                f"{self.title!r}: {len(matches)} issues found."
            )
        return matches[0] if matches else None

    def create_issue(self, *, project_id: str, body: str) -> GitLabIssueInfo:
        """Create the authoritative policy issue."""
        return self.client.create_issue(
            project_id=project_id,
            title=self.title,
            description=body,
            labels=self.labels,
        )

    def update_issue_body(
        self,
        *,
        project_id: str,
        issue: GitLabIssueInfo,
        body: str,
    ) -> GitLabIssueInfo:
        """Persist one rendered policy issue body update."""
        return self.client.update_issue(
            project_id=project_id,
            issue_iid=issue.iid,
            title=self.title,
            description=body,
            labels=self.labels,
        )
