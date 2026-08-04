from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.services.control_plane.overview.github_operational_summary_store import (
    GitHubOperationalSummaryStore,
)


class FakeSummaryIssueClient:
    def __init__(self) -> None:
        self.issue: GitHubIssueInfo | None = None
        self.find_arguments: tuple[str, str, list[str] | None] | None = None

    def find_open_issue(
        self,
        *,
        repository_id: str,
        title: str,
        labels: list[str] | None = None,
    ) -> GitHubIssueInfo | None:
        self.find_arguments = (repository_id, title, labels)
        return self.issue

    def create_issue(
        self,
        *,
        repository_id: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> GitHubIssueInfo:
        self.issue = GitHubIssueInfo(
            id=1,
            number=2,
            web_url=f"https://github.example.com/{repository_id}/issues/2",
            title=title,
            body=body,
        )
        assert labels == ["zeroone-summary"]
        return self.issue

    def update_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
        body: str,
    ) -> GitHubIssueInfo:
        assert self.issue is not None
        assert repository_id == "octo-org/octo-repo"
        assert issue_number == self.issue.number
        self.issue = self.issue.model_copy(update={"body": body})
        return self.issue


def test_store_uses_dedicated_title_and_label() -> None:
    client = FakeSummaryIssueClient()
    store = GitHubOperationalSummaryStore(client)

    assert store.find_open_issue(repository_id="octo-org/octo-repo") is None
    assert client.find_arguments == (
        "octo-org/octo-repo",
        "ZeroOne Ops Summary",
        ["zeroone-summary"],
    )

    issue = store.create_issue(repository_id="octo-org/octo-repo", body="first")
    updated = store.update_issue_body(
        repository_id="octo-org/octo-repo",
        issue_number=issue.number,
        body="second",
    )

    assert issue.title == "ZeroOne Ops Summary"
    assert updated.body == "second"
