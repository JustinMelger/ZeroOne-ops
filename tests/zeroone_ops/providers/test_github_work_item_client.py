from __future__ import annotations

import httpx

from zeroone_ops.models.config import GitHubConnectionConfig
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
