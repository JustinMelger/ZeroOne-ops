import pytest

from zeroone_ops.models.config import GitLabConnectionConfig
from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.providers.gitlab_policy_client import GitLabPolicyClient
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_store import (
    GitLabPolicyIssueStore,
)


class FakeIssueClient:
    def __init__(self, issues: list[GitLabIssueInfo]) -> None:
        self.issues = issues
        self.updated: tuple[int, str, str, list[str]] | None = None

    def list_open_issues(self, *, project_id: str, labels: list[str]) -> list[GitLabIssueInfo]:
        del project_id, labels
        return self.issues

    def create_issue(
        self, *, project_id: str, title: str, description: str, labels: list[str]
    ) -> GitLabIssueInfo:
        del project_id
        return _issue(iid=2, title=title, description=description, labels=labels)

    def update_issue(
        self,
        *,
        project_id: str,
        issue_iid: int,
        title: str,
        description: str,
        labels: list[str],
    ) -> GitLabIssueInfo:
        del project_id
        self.updated = (issue_iid, title, description, labels)
        return _issue(iid=issue_iid, title=title, description=description, labels=labels)


def _issue(
    *,
    iid: int,
    title: str = "ZeroOne Ops Policy",
    description: str = "old",
    labels: list[str] | None = None,
) -> GitLabIssueInfo:
    return GitLabIssueInfo(
        id=1,
        iid=iid,
        web_url=f"https://gitlab.example.com/issues/{iid}",
        title=title,
        description=description,
        labels=labels or [],
    )


def build_store(fake: FakeIssueClient) -> GitLabPolicyIssueStore:
    client = GitLabPolicyClient(
        GitLabConnectionConfig(url="https://gitlab.example.com", token="token", project_id="1"),
        issue_client=fake,  # type: ignore[arg-type]
    )
    return GitLabPolicyIssueStore(client, title="ZeroOne Ops Policy", labels=["zeroone-policy"])


def test_store_finds_exact_open_policy_issue_and_persists_managed_labels() -> None:
    issue = _issue(iid=2)
    fake = FakeIssueClient([issue])
    store = build_store(fake)

    found = store.find_open_issue(project_id="group/project")
    updated = store.update_issue_body(project_id="group/project", issue=issue, body="new")

    assert found == issue
    assert updated.description == "new"
    assert fake.updated == (2, "ZeroOne Ops Policy", "new", ["zeroone-policy"])


def test_policy_client_rejects_duplicate_exact_matches() -> None:
    issue = _issue(iid=2)
    with pytest.raises(GitLabClientError, match="Ambiguous GitLab policy issue"):
        build_store(FakeIssueClient([issue, issue])).find_open_issue(project_id="group/project")
