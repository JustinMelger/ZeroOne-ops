from __future__ import annotations

import httpx
import pytest

from zeroone_ops.models.config import GitHubConnectionConfig
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient


def build_config() -> GitHubConnectionConfig:
    return GitHubConnectionConfig(
        api_url="https://api.github.example.com",
        server_url="https://github.example.com",
        token="token",
        repository="octo-org/octo-repo",
    )


def test_list_open_issues_ignores_pull_requests_and_normalizes_issues() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/issues"
        assert request.url.params["state"] == "open"
        assert request.url.params["labels"] == "zeroone-work-item"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "number": 10,
                    "html_url": "https://github/x/10",
                    "title": "PR masquerading as issue",
                    "body": "",
                    "pull_request": {"url": "https://api.github/x"},
                },
                {
                    "id": 2,
                    "number": 11,
                    "html_url": "https://github/x/11",
                    "title": "ZeroOne Ops: Remediate item",
                    "body": "body",
                    "created_at": "2026-07-26T09:30:00Z",
                    "updated_at": "2026-07-27T10:30:00Z",
                },
            ],
        )

    client = GitHubWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    issues = client.list_open_issues(
        repository_id="octo-org/octo-repo",
        labels=["zeroone-work-item"],
    )

    assert len(issues) == 1
    assert issues[0].number == 11
    assert issues[0].created_at is not None
    assert issues[0].updated_at is not None


def test_list_closed_issues_requests_closed_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/issues"
        assert request.url.params["state"] == "closed"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 2,
                    "number": 11,
                    "html_url": "https://github/x/11",
                    "title": "Closed work item",
                    "body": "body",
                    "updated_at": "2026-07-27T10:30:00Z",
                }
            ],
        )

    client = GitHubWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    issues = client.list_closed_issues(repository_id="octo-org/octo-repo")

    assert [issue.number for issue in issues] == [11]
    assert issues[0].updated_at is not None


def test_list_open_issues_paginates_until_exhaustion() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(int(request.url.params["page"]))
        assert request.url.path == "/repos/octo-org/octo-repo/issues"
        assert request.url.params["state"] == "open"
        assert request.url.params["labels"] == "zeroone-work-item"
        if request.url.params["page"] == "1":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "number": 10,
                        "html_url": "https://github/x/10",
                        "title": "First page",
                        "body": "body-1",
                    }
                ],
                headers={
                    "Link": (
                        "<https://api.github.example.com/repos/octo-org/octo-repo/"
                        'issues?page=2&per_page=100>; rel="next"'
                    )
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": 2,
                    "number": 11,
                    "html_url": "https://github/x/11",
                    "title": "Second page",
                    "body": "body-2",
                }
            ],
        )

    client = GitHubWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    issues = client.list_open_issues(
        repository_id="octo-org/octo-repo",
        labels=["zeroone-work-item"],
    )

    assert calls == [1, 2]
    assert [issue.number for issue in issues] == [10, 11]


def test_list_open_issues_rejects_timestamp_without_timezone() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": 2,
                    "number": 11,
                    "html_url": "https://github/x/11",
                    "title": "ZeroOne Ops: Remediate item",
                    "body": "body",
                    "created_at": "2026-07-26T09:30:00",
                }
            ],
        )

    client = GitHubWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    with pytest.raises(GitHubClientError, match="creation timestamp"):
        client.list_open_issues(repository_id="octo-org/octo-repo")


def test_create_issue_posts_expected_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/issues"
        assert request.method == "POST"
        assert request.content.decode("utf-8") == (
            '{"title":"ZeroOne Ops: Remediate item","body":"body","labels":["zeroone-work-item"]}'
        )
        return httpx.Response(
            201,
            json={
                "id": 2,
                "number": 11,
                "html_url": "https://github/x/11",
                "title": "ZeroOne Ops: Remediate item",
                "body": "body",
            },
        )

    client = GitHubWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    issue = client.create_issue(
        repository_id="octo-org/octo-repo",
        title="ZeroOne Ops: Remediate item",
        body="body",
        labels=["zeroone-work-item"],
    )

    assert issue.number == 11


def test_update_issue_patches_expected_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/issues/11"
        assert request.method == "PATCH"
        assert request.content.decode("utf-8") == (
            '{"title":"ZeroOne Ops: Remediate item","body":"updated",'
            '"labels":["zeroone-work-item","zeroone-status:approved"]}'
        )
        return httpx.Response(
            200,
            json={
                "id": 2,
                "number": 11,
                "html_url": "https://github/x/11",
                "title": "ZeroOne Ops: Remediate item",
                "body": "updated",
            },
        )

    client = GitHubWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    issue = client.update_issue(
        repository_id="octo-org/octo-repo",
        issue_number=11,
        title="ZeroOne Ops: Remediate item",
        body="updated",
        labels=["zeroone-work-item", "zeroone-status:approved"],
    )

    assert issue.body == "updated"


def test_close_issue_patches_closed_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/issues/11"
        assert request.method == "PATCH"
        assert request.content.decode("utf-8") == '{"state":"closed"}'
        return httpx.Response(
            200,
            json={
                "id": 2,
                "number": 11,
                "html_url": "https://github/x/11",
                "title": "ZeroOne Ops: Remediate item",
                "body": "body",
            },
        )

    client = GitHubWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    issue = client.close_issue(repository_id="octo-org/octo-repo", issue_number=11)

    assert issue.number == 11


def test_list_issue_comments_and_repository_permission_use_work_item_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            assert request.url.params["page"] == "1"
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 21,
                        "html_url": "https://github/x/issues/11#issuecomment-21",
                        "body": "/zeroone remediation retry",
                        "created_at": "2026-08-07T09:00:00Z",
                        "user": {"login": "operator"},
                    }
                ],
            )
        assert request.url.path == "/repos/octo-org/octo-repo/collaborators/operator/permission"
        return httpx.Response(200, json={"role_name": "admin"})

    client = GitHubWorkItemClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    comments = client.list_issue_comments(repository_id="octo-org/octo-repo", issue_number=11)
    permission = client.get_repository_permission(
        repository_id="octo-org/octo-repo",
        username="operator",
    )

    assert comments[0].id == 21
    assert comments[0].author_username == "operator"
    assert permission == "admin"
