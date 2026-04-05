from __future__ import annotations

import httpx

from ai_sonar_bot.models.config import GitLabConnectionConfig
from ai_sonar_bot.providers.gitlab_dashboard_client import GitLabDashboardClient


def build_config() -> GitLabConnectionConfig:
    return GitLabConnectionConfig(
        url="https://gitlab.example.com",
        token="token",
        project_id="123",
    )


def test_find_open_issue_returns_exact_title_match() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/issues"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 1,
                    "iid": 2,
                    "web_url": "https://gitlab.example.com/group/project/-/issues/2",
                    "title": "Not the dashboard",
                    "description": "body",
                },
                {
                    "id": 3,
                    "iid": 4,
                    "web_url": "https://gitlab.example.com/group/project/-/issues/4",
                    "title": "AI Code Ops Dashboard",
                    "description": "body",
                },
            ],
        )

    client = GitLabDashboardClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    issue = client.find_open_issue(
        project_id="123",
        title="AI Code Ops Dashboard",
        labels=["ai-code-ops", "dashboard"],
    )

    assert issue is not None
    assert issue.iid == 4


def test_create_issue_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/issues"
        assert request.method == "POST"
        return httpx.Response(
            201,
            json={
                "id": 10,
                "iid": 11,
                "web_url": "https://gitlab.example.com/group/project/-/issues/11",
                "title": "AI Code Ops Dashboard",
                "description": "body",
            },
        )

    client = GitLabDashboardClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    issue = client.create_issue(
        project_id="123",
        title="AI Code Ops Dashboard",
        description="body",
        labels=["ai-code-ops", "dashboard"],
    )

    assert issue.id == 10
    assert issue.iid == 11


def test_update_issue_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/issues/11"
        assert request.method == "PUT"
        return httpx.Response(
            200,
            json={
                "id": 10,
                "iid": 11,
                "web_url": "https://gitlab.example.com/group/project/-/issues/11",
                "title": "AI Code Ops Dashboard",
                "description": "updated body",
            },
        )

    client = GitLabDashboardClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    issue = client.update_issue(
        project_id="123",
        issue_iid=11,
        description="updated body",
    )

    assert issue.description == "updated body"
