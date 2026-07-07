from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.services.remediation.change_request_publisher import (
    ChangeRequestPublishRequest,
    GitHubRemediationChangeRequestPublisher,
    GitLabRemediationChangeRequestPublisher,
)


class StubGitLabClient:
    def __init__(self) -> None:
        self.config = type("Config", (), {"project_id": "group/project"})()
        self.assignee_username: str | None = None
        self.assignee_update: tuple[int, int] | None = None
        self.created_request: ChangeRequestPublishRequest | None = None
        self.existing: ChangeRequestInfo | None = None

    def find_user_id_by_username(self, username: str) -> int:
        self.assignee_username = username
        return 42

    def find_open_merge_request(
        self,
        *,
        project_id: str,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequestInfo | None:
        del project_id, source_branch, target_branch
        return self.existing

    def update_merge_request_assignee(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        assignee_id: int,
    ) -> None:
        del project_id
        self.assignee_update = (merge_request_iid, assignee_id)

    def create_merge_request(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str] | None = None,
        assignee_id: int | None = None,
    ) -> ChangeRequestInfo:
        del project_id, assignee_id
        self.created_request = ChangeRequestPublishRequest(
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
            labels=labels or [],
        )
        return ChangeRequestInfo(
            iid=18,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/18",
            title=title,
        )


class StubGitHubClient:
    def __init__(self) -> None:
        self.config = type("Config", (), {"repository": "octo-org/octo-repo"})()
        self.assignee_username: str | None = None
        self.created_request: ChangeRequestPublishRequest | None = None
        self.created_issue_number: int | None = None
        self.labels_issue_number: int | None = None
        self.labels: list[str] | None = None
        self.existing: ChangeRequestInfo | None = None
        self.fail_label_update = False
        self.fail_assign_issue = False

    def find_open_pull_request(
        self,
        *,
        repository_id: str,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequestInfo | None:
        del repository_id, source_branch, target_branch
        return self.existing

    def create_pull_request(
        self,
        *,
        repository_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> ChangeRequestInfo:
        del repository_id
        self.created_request = ChangeRequestPublishRequest(
            source_branch=source_branch,
            target_branch=target_branch,
            title=title,
            description=description,
            labels=[],
        )
        created = ChangeRequestInfo(
            iid=19,
            web_url="https://github.com/octo-org/octo-repo/pull/19",
            title=title,
        )
        self.created_issue_number = created.iid
        return created

    def add_issue_labels(
        self,
        *,
        repository_id: str,
        issue_number: int,
        labels: list[str],
    ) -> None:
        del repository_id
        if self.fail_label_update:
            raise GitHubClientError("label update failed")
        self.labels_issue_number = issue_number
        self.labels = labels

    def assign_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
        assignee_username: str,
    ) -> None:
        del repository_id, issue_number
        if self.fail_assign_issue:
            raise GitHubClientError("assign issue failed")
        self.assignee_username = assignee_username


def test_gitlab_change_request_publisher_reuses_existing_change_request() -> None:
    client = StubGitLabClient()
    client.existing = ChangeRequestInfo(
        iid=17,
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        title="fix: remediate python:S2259 in service.py",
    )
    publisher = GitLabRemediationChangeRequestPublisher(client)  # type: ignore[arg-type]

    result = publisher.publish(
        ChangeRequestPublishRequest(
            source_branch="zeroone-ops/fix",
            target_branch="main",
            title="fix: remediate python:S2259 in service.py",
            description="summary",
            labels=["zeroone-ops"],
            assignee_username="justin",
        )
    )

    assert result.action == "reused"
    assert client.assignee_username == "justin"
    assert client.assignee_update == (17, 42)


def test_gitlab_change_request_publisher_creates_change_request_when_missing() -> None:
    client = StubGitLabClient()
    publisher = GitLabRemediationChangeRequestPublisher(client)  # type: ignore[arg-type]

    result = publisher.publish(
        ChangeRequestPublishRequest(
            source_branch="zeroone-ops/fix",
            target_branch="main",
            title="fix: remediate python:S2259 in service.py",
            description="summary",
            labels=["zeroone-ops"],
        )
    )

    assert result.action == "created"
    assert client.created_request is not None
    assert client.created_request.source_branch == "zeroone-ops/fix"
    assert client.created_request.target_branch == "main"


def test_github_change_request_publisher_reuses_existing_change_request() -> None:
    client = StubGitHubClient()
    client.existing = ChangeRequestInfo(
        iid=17,
        web_url="https://github.com/octo-org/octo-repo/pull/17",
        title="fix: remediate python:S2259 in service.py",
    )
    publisher = GitHubRemediationChangeRequestPublisher(client)  # type: ignore[arg-type]

    result = publisher.publish(
        ChangeRequestPublishRequest(
            source_branch="zeroone-ops/fix",
            target_branch="main",
            title="fix: remediate python:S2259 in service.py",
            description="summary",
            labels=["zeroone-ops"],
            assignee_username="justin",
        )
    )

    assert result.action == "reused"
    assert client.assignee_username == "justin"
    assert client.labels is None


def test_github_change_request_publisher_creates_change_request_when_missing() -> None:
    client = StubGitHubClient()
    publisher = GitHubRemediationChangeRequestPublisher(client)  # type: ignore[arg-type]

    result = publisher.publish(
        ChangeRequestPublishRequest(
            source_branch="zeroone-ops/fix",
            target_branch="main",
            title="fix: remediate python:S2259 in service.py",
            description="summary",
            labels=["zeroone-ops"],
            assignee_username="justin",
        )
    )

    assert result.action == "created"
    assert client.created_request is not None
    assert client.created_request.source_branch == "zeroone-ops/fix"
    assert client.created_request.target_branch == "main"
    assert client.labels_issue_number == 19
    assert client.labels == ["zeroone-ops"]
    assert client.assignee_username == "justin"


def test_github_change_request_publisher_keeps_created_result_when_label_update_fails() -> None:
    client = StubGitHubClient()
    client.fail_label_update = True
    publisher = GitHubRemediationChangeRequestPublisher(client)  # type: ignore[arg-type]

    result = publisher.publish(
        ChangeRequestPublishRequest(
            source_branch="zeroone-ops/fix",
            target_branch="main",
            title="fix: remediate python:S2259 in service.py",
            description="summary",
            labels=["zeroone-ops"],
        )
    )

    assert result.action == "created"
    assert result.info.web_url == "https://github.com/octo-org/octo-repo/pull/19"


def test_github_change_request_publisher_keeps_created_result_when_assign_fails() -> None:
    client = StubGitHubClient()
    client.fail_assign_issue = True
    publisher = GitHubRemediationChangeRequestPublisher(client)  # type: ignore[arg-type]

    result = publisher.publish(
        ChangeRequestPublishRequest(
            source_branch="zeroone-ops/fix",
            target_branch="main",
            title="fix: remediate python:S2259 in service.py",
            description="summary",
            labels=["zeroone-ops"],
            assignee_username="justin",
        )
    )

    assert result.action == "created"
    assert result.info.web_url == "https://github.com/octo-org/octo-repo/pull/19"
