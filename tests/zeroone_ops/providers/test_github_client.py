from __future__ import annotations

import httpx

from zeroone_ops.models.config import GitHubConnectionConfig
from zeroone_ops.providers.github_client import GitHubClient


def build_config() -> GitHubConnectionConfig:
    return GitHubConnectionConfig(
        api_url="https://api.github.example.com",
        server_url="https://github.example.com",
        token="token",
        repository="octo-org/octo-repo",
    )


def test_find_open_pull_request_returns_none_for_empty_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/pulls"
        assert request.method == "GET"
        assert request.url.params["state"] == "open"
        assert request.url.params["head"] == "octo-org:zeroone-ops/fix"
        assert request.url.params["base"] == "main"
        return httpx.Response(200, json=[])

    client = GitHubClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    pull_request = client.find_open_pull_request(
        repository_id="octo-org/octo-repo",
        source_branch="zeroone-ops/fix",
        target_branch="main",
    )

    assert pull_request is None


def test_find_open_pull_request_normalizes_existing_pull_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/pulls"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=[
                {
                    "number": 17,
                    "html_url": "https://github.com/octo-org/octo-repo/pull/17",
                    "title": "fix: patch service",
                }
            ],
        )

    client = GitHubClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    pull_request = client.find_open_pull_request(
        repository_id="octo-org/octo-repo",
        source_branch="zeroone-ops/fix",
        target_branch="main",
    )

    assert pull_request is not None
    assert pull_request.iid == 17
    assert pull_request.web_url == "https://github.com/octo-org/octo-repo/pull/17"
    assert pull_request.title == "fix: patch service"


def test_create_pull_request_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/pulls"
        assert request.method == "POST"
        assert request.content.decode("utf-8") == (
            '{"title":"fix: patch service","body":"summary","head":"zeroone-ops/fix","base":"main"}'
        )
        return httpx.Response(
            201,
            json={
                "number": 21,
                "html_url": "https://github.com/octo-org/octo-repo/pull/21",
                "title": "fix: patch service",
            },
        )

    client = GitHubClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    pull_request = client.create_pull_request(
        repository_id="octo-org/octo-repo",
        source_branch="zeroone-ops/fix",
        target_branch="main",
        title="fix: patch service",
        description="summary",
    )

    assert pull_request.iid == 21
    assert pull_request.web_url == "https://github.com/octo-org/octo-repo/pull/21"


def test_get_branch_head_sha_reads_remote_reference() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/git/ref/heads/zeroone-ops/fix"
        assert request.method == "GET"
        return httpx.Response(200, json={"object": {"sha": "abc123"}})

    client = GitHubClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    sha = client.get_branch_head_sha(
        repository_id="octo-org/octo-repo",
        branch_name="zeroone-ops/fix",
    )

    assert sha == "abc123"


def test_get_branch_head_sha_returns_none_when_remote_branch_is_missing() -> None:
    client = GitHubClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(404, json={})),
            base_url="https://api.github.example.com",
        ),
    )

    sha = client.get_branch_head_sha(
        repository_id="octo-org/octo-repo",
        branch_name="zeroone-ops/missing",
    )

    assert sha is None


def test_add_issue_labels_posts_expected_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/issues/21/labels"
        assert request.method == "POST"
        assert request.content.decode("utf-8") == '{"labels":["zeroone-ops","autofix"]}'
        return httpx.Response(200, json=[{"name": "zeroone-ops"}, {"name": "autofix"}])

    client = GitHubClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    client.add_issue_labels(
        repository_id="octo-org/octo-repo",
        issue_number=21,
        labels=["zeroone-ops", "autofix"],
    )


def test_assign_issue_posts_expected_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/issues/21/assignees"
        assert request.method == "POST"
        assert request.content.decode("utf-8") == '{"assignees":["justin"]}'
        return httpx.Response(201, json={"assignees": [{"login": "justin"}]})

    client = GitHubClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    client.assign_issue(
        repository_id="octo-org/octo-repo",
        issue_number=21,
        assignee_username="justin",
    )


def test_github_enterprise_base_path_is_preserved_for_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/repos/octo-org/octo-repo/pulls"
        assert request.method == "GET"
        return httpx.Response(200, json=[])

    client = GitHubClient(
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

    pull_request = client.find_open_pull_request(
        repository_id="octo-org/octo-repo",
        source_branch="zeroone-ops/fix",
        target_branch="main",
    )

    assert pull_request is None


def test_get_pull_request_state_normalizes_open_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo-org/octo-repo/pulls/21"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "number": 21,
                "html_url": "https://github.com/octo-org/octo-repo/pull/21",
                "state": "open",
                "merged_at": None,
                "head": {
                    "ref": "zeroone-ops/fix",
                    "sha": "abc123",
                },
            },
        )

    client = GitHubClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    pull_request = client.get_pull_request_state(
        repository_id="octo-org/octo-repo",
        pull_request_number=21,
    )

    assert pull_request.iid == 21
    assert pull_request.state == "opened"
    assert pull_request.source_branch == "zeroone-ops/fix"
    assert pull_request.head_sha == "abc123"


def test_get_pull_request_state_normalizes_merged_state() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "number": 21,
                "html_url": "https://github.com/octo-org/octo-repo/pull/21",
                "state": "closed",
                "merged_at": "2026-07-10T12:00:00Z",
                "head": {
                    "ref": "zeroone-ops/fix",
                    "sha": "abc123",
                },
            },
        )

    client = GitHubClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.github.example.com",
        ),
    )

    pull_request = client.get_pull_request_state(
        repository_id="octo-org/octo-repo",
        pull_request_number=21,
    )

    assert pull_request.state == "merged"
