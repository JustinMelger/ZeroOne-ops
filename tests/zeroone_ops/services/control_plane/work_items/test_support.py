from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState


def build_work_item(*, status: str = "approved") -> WorkItemState:
    return WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status=status,  # type: ignore[arg-type]
        source=WorkItemSourceRef(
            source="sonarqube",
            source_item_key="AX123",
            repository_scope="octo-org/octo-repo",
        ),
        summary="Remediate Sonar issue AX123 in api.py",
        severity="high",
        file_path="src/api.py",
        line=42,
    )


class FakeGitHubWorkItemClient:
    def __init__(self) -> None:
        self.issues: list[GitHubIssueInfo] = []
        self.closed_issues: list[GitHubIssueInfo] = []
        self.created_issue: GitHubIssueInfo | None = None
        self.updated_issue: GitHubIssueInfo | None = None
        self.list_labels: list[str] | None = None

    def list_open_issues(
        self,
        *,
        repository_id: str,
        labels: list[str] | None = None,
    ) -> list[GitHubIssueInfo]:
        del repository_id
        self.list_labels = labels
        return list(self.issues)

    def list_closed_issues(
        self,
        *,
        repository_id: str,
        labels: list[str] | None = None,
    ) -> list[GitHubIssueInfo]:
        del repository_id
        self.list_labels = labels
        return list(self.closed_issues)

    def create_issue(
        self,
        *,
        repository_id: str,
        title: str,
        body: str,
        labels: list[str],
    ) -> GitHubIssueInfo:
        del repository_id, labels
        self.created_issue = GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=title,
            body=body,
        )
        self.issues = [self.created_issue]
        return self.created_issue

    def update_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
        title: str,
        body: str,
        labels: list[str],
    ) -> GitHubIssueInfo:
        del repository_id, issue_number, labels
        assert self.issues
        self.updated_issue = GitHubIssueInfo(
            id=self.issues[0].id,
            number=self.issues[0].number,
            web_url=self.issues[0].web_url,
            title=title,
            body=body,
        )
        self.issues = [self.updated_issue]
        return self.updated_issue
