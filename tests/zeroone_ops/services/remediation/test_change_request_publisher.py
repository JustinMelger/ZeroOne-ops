from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.services.remediation.change_request_publisher import (
    ChangeRequestPublishRequest,
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
