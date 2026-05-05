from __future__ import annotations

import httpx
import pytest

from zeroone_ops.models.config import GitLabConnectionConfig
from zeroone_ops.providers.gitlab_client import GitLabClient, GitLabClientError


def build_config() -> GitLabConnectionConfig:
    return GitLabConnectionConfig(
        url="https://gitlab.example.com",
        token="token",
        project_id="123",
    )


def test_create_merge_request_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests"
        assert request.method == "POST"
        return httpx.Response(
            201,
            json={
                "iid": 7,
                "web_url": "https://gitlab.example.com/group/project/-/merge_requests/7",
                "title": "fix: patch service",
            },
        )

    client = GitLabClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    mr = client.create_merge_request(
        project_id="123",
        source_branch="zeroone-ops/ax-1/service",
        target_branch="main",
        title="fix: patch service",
        description="summary",
        labels=["ai-sonar-bot"],
    )

    assert mr.iid == 7
    assert mr.title == "fix: patch service"


def test_find_open_merge_request_returns_none_for_empty_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests"
        assert request.method == "GET"
        return httpx.Response(200, json=[])

    client = GitLabClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    mr = client.find_open_merge_request(
        project_id="123",
        source_branch="zeroone-ops/ax-1/service",
        target_branch="main",
    )

    assert mr is None


def test_find_open_merge_request_normalizes_existing_merge_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=[
                {
                    "iid": 9,
                    "web_url": "https://gitlab.example.com/group/project/-/merge_requests/9",
                    "title": "fix: patch service",
                }
            ],
        )

    client = GitLabClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    mr = client.find_open_merge_request(
        project_id="123",
        source_branch="zeroone-ops/ax-1/service",
        target_branch="main",
    )

    assert mr is not None
    assert mr.iid == 9
    assert mr.web_url == "https://gitlab.example.com/group/project/-/merge_requests/9"


def test_find_open_merge_request_reports_invalid_or_expired_token_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests"
        return httpx.Response(401, json={"message": "401 Unauthorized"})

    client = GitLabClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    with pytest.raises(GitLabClientError, match="invalid or expired"):
        client.find_open_merge_request(
            project_id="123",
            source_branch="zeroone-ops/ax-1/service",
            target_branch="main",
        )


def test_find_open_merge_request_reports_permission_problem_on_403() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests"
        return httpx.Response(403, json={"message": "403 Forbidden"})

    client = GitLabClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    with pytest.raises(GitLabClientError, match="does not have permission"):
        client.find_open_merge_request(
            project_id="123",
            source_branch="zeroone-ops/ax-1/service",
            target_branch="main",
        )
