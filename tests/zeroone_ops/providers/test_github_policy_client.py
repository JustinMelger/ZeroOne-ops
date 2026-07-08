from __future__ import annotations

import httpx

from zeroone_ops.models.config import GitHubConnectionConfig
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.github_policy_client import GitHubPolicyClient


def build_config() -> GitHubConnectionConfig:
    return GitHubConnectionConfig(
        api_url="https://api.github.example.com",
        server_url="https://github.example.com",
        token="token",
        repository="octo-org/octo-repo",
    )


def test_find_open_issue_returns_none_when_no_exact_match_exists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/issues"
        assert request.method == "GET"
        assert request.url.params["state"] == "open"
        assert request.url.params["labels"] == "zeroone-policy"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "number": 10,
                    "html_url": "https://github/x/10",
                    "title": "Other",
                    "body": "",
                }
            ],
        )

    client = GitHubPolicyClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    issue = client.find_open_issue(
        repository_id="octo-org/octo-repo",
        title="ZeroOne Ops Policy",
        labels=["zeroone-policy"],
    )

    assert issue is None


def test_find_open_issue_rejects_ambiguous_exact_matches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "number": 10,
                    "html_url": "https://github/x/10",
                    "title": "ZeroOne Ops Policy",
                    "body": "",
                },
                {
                    "id": 2,
                    "number": 11,
                    "html_url": "https://github/x/11",
                    "title": "ZeroOne Ops Policy",
                    "body": "",
                },
            ],
        )

    client = GitHubPolicyClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    try:
        client.find_open_issue(
            repository_id="octo-org/octo-repo",
            title="ZeroOne Ops Policy",
            labels=["zeroone-policy"],
        )
    except GitHubClientError as error:
        assert "Ambiguous GitHub policy issue match" in str(error)
    else:
        raise AssertionError("Expected GitHubClientError for ambiguous policy issue matches.")


def test_find_open_issue_ignores_pull_requests_and_normalizes_issue() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": 99,
                    "number": 12,
                    "html_url": "https://github/x/12",
                    "title": "ZeroOne Ops Policy",
                    "body": "",
                    "pull_request": {"url": "https://api.github/x"},
                },
                {
                    "id": 100,
                    "number": 13,
                    "html_url": "https://github/x/13",
                    "title": "ZeroOne Ops Policy",
                    "body": "policy body",
                },
            ],
        )

    client = GitHubPolicyClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    issue = client.find_open_issue(
        repository_id="octo-org/octo-repo",
        title="ZeroOne Ops Policy",
        labels=["zeroone-policy"],
    )

    assert issue is not None
    assert issue.number == 13
    assert issue.body == "policy body"


def test_create_issue_posts_expected_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/issues"
        assert request.method == "POST"
        assert request.content.decode("utf-8") == (
            '{"title":"ZeroOne Ops Policy","body":"policy body","labels":["zeroone-policy"]}'
        )
        return httpx.Response(
            201,
            json={
                "id": 100,
                "number": 13,
                "html_url": "https://github/x/13",
                "title": "ZeroOne Ops Policy",
                "body": "policy body",
            },
        )

    client = GitHubPolicyClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    issue = client.create_issue(
        repository_id="octo-org/octo-repo",
        title="ZeroOne Ops Policy",
        body="policy body",
        labels=["zeroone-policy"],
    )

    assert issue.number == 13


def test_update_issue_patches_expected_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/issues/13"
        assert request.method == "PATCH"
        assert request.content.decode("utf-8") == '{"body":"updated body"}'
        return httpx.Response(
            200,
            json={
                "id": 100,
                "number": 13,
                "html_url": "https://github/x/13",
                "title": "ZeroOne Ops Policy",
                "body": "updated body",
            },
        )

    client = GitHubPolicyClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    issue = client.update_issue(
        repository_id="octo-org/octo-repo",
        issue_number=13,
        body="updated body",
    )

    assert issue.body == "updated body"


def test_list_issue_comments_normalizes_paginated_comments() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(int(request.url.params["page"]))
        assert request.url.path == "/repos/octo-org/octo-repo/issues/13/comments"
        if request.url.params["page"] == "1":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "html_url": "https://github/x/comments/1",
                        "body": "first",
                        "created_at": "2026-07-08T10:00:00Z",
                        "user": {"login": "justin"},
                    }
                ],
                headers={
                    "Link": (
                        "<https://api.github.example.com/repos/octo-org/octo-repo/"
                        'issues/13/comments?page=2&per_page=100>; rel="next"'
                    )
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": 2,
                    "html_url": "https://github/x/comments/2",
                    "body": "second",
                    "created_at": "2026-07-08T10:01:00Z",
                    "user": {"login": "octocat"},
                }
            ],
        )

    client = GitHubPolicyClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    comments = client.list_issue_comments(
        repository_id="octo-org/octo-repo",
        issue_number=13,
    )

    assert calls == [1, 2]
    assert [comment.id for comment in comments] == [1, 2]
    assert comments[0].author_username == "justin"


def test_github_enterprise_base_path_is_preserved_for_policy_issue_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/repos/octo-org/octo-repo/issues"
        assert request.method == "GET"
        return httpx.Response(200, json=[])

    client = GitHubPolicyClient(
        GitHubConnectionConfig(
            api_url="https://github.example.com/api/v3",
            server_url="https://github.example.com",
            token="token",
            repository="octo-org/octo-repo",
        ),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://github.example.com/api/v3",
        ),
    )

    issue = client.find_open_issue(
        repository_id="octo-org/octo-repo",
        title="ZeroOne Ops Policy",
        labels=["zeroone-policy"],
    )

    assert issue is None


def test_get_repository_permission_returns_role_name_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert (
            request.url.path
            == "/repos/octo-org/octo-repo/collaborators/justin/permission"
        )
        assert request.method == "GET"
        return httpx.Response(200, json={"permission": "write", "role_name": "admin"})

    client = GitHubPolicyClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    permission = client.get_repository_permission(
        repository_id="octo-org/octo-repo",
        username="justin",
    )

    assert permission == "admin"
