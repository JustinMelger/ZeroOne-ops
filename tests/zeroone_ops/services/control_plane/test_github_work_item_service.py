from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.control_plane.github_work_item_parser import GitHubWorkItemParser
from zeroone_ops.services.control_plane.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)
from zeroone_ops.services.control_plane.github_work_item_service import (
    GitHubWorkItemService,
)


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


def test_github_work_item_renderer_and_parser_round_trip() -> None:
    renderer = GitHubWorkItemRenderer()
    parser = GitHubWorkItemParser()

    body = renderer.render_body(build_work_item())
    parsed = parser.parse_work_item_state(body)

    assert parsed is not None
    assert parsed.work_item_id == "work-1"
    assert parsed.identity_key == build_work_item().identity_key


def test_github_work_item_service_creates_when_identity_is_missing() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubWorkItemService(client)  # type: ignore[arg-type]

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(),
    )

    assert result.action == "created"
    assert result.work_item.work_item_id == "work-1"
    assert client.created_issue is not None
    assert client.created_issue.title == "ZeroOne Ops: Remediate Sonar issue AX123 in api.py"


def test_github_work_item_service_updates_matching_open_issue_when_state_changes() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item(status="approved")
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemService(client)  # type: ignore[arg-type]

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(status="in_progress"),
    )

    assert result.action == "updated"
    assert result.work_item.work_item_id == "work-1"
    assert client.updated_issue is not None
    assert client.list_labels == ["zeroone-work-item"]
    assert "`in_progress`" in client.updated_issue.body


def test_github_work_item_service_reuses_matching_open_issue_without_title_authority() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item()
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title="Operator renamed this title",
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemService(client)  # type: ignore[arg-type]

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=original,
    )

    assert result.action == "updated"
    assert result.work_item.work_item_id == "work-1"
    assert client.updated_issue is not None
    assert client.updated_issue.title == renderer.render_title(original)


def test_github_work_item_service_skips_malformed_issue_state_during_scan() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item()
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=9,
            number=10,
            web_url="https://github.example.com/octo-org/octo-repo/issues/10",
            title="Malformed work item",
            body=(
                "<details>\n"
                "<summary><code>zeroone-work-item-state</code> machine state</summary>\n\n"
                "```json\n"
                "{not-json}\n"
                "```\n\n"
                "</details>\n"
            ),
        ),
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        ),
    ]
    service = GitHubWorkItemService(client)  # type: ignore[arg-type]

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(status="in_progress"),
    )

    assert result.action == "updated"
    assert result.work_item.work_item_id == "work-1"
    assert client.updated_issue is not None


def test_github_work_item_service_filters_reuse_scan_to_authoritative_work_item_label() -> None:
    renderer = GitHubWorkItemRenderer()
    original = build_work_item()
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemService(client)  # type: ignore[arg-type]

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(status="blocked"),
    )

    assert result.action == "updated"
    assert result.work_item.work_item_id == "work-1"
    assert client.updated_issue is not None
    assert client.list_labels == ["zeroone-work-item"]


def test_github_work_item_service_preserves_existing_link_when_retry_has_no_replacement() -> None:
    renderer = GitHubWorkItemRenderer()
    linked_change_request = ChangeRequestRef(
        number=17,
        web_url="https://github.example.com/octo-org/octo-repo/pull/17",
    )
    original = build_work_item().model_copy(update={"linked_change_request": linked_change_request})
    client = FakeGitHubWorkItemClient()
    client.issues = [
        GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=renderer.render_title(original),
            body=renderer.render_body(original),
        )
    ]
    service = GitHubWorkItemService(client)  # type: ignore[arg-type]

    result = service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(status="blocked"),
    )

    assert result.action == "updated"
    assert result.work_item.work_item_id == "work-1"
    assert result.work_item.linked_change_request == linked_change_request
    assert client.updated_issue is not None
    assert "pull/17" in client.updated_issue.body
