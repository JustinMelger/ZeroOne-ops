from __future__ import annotations

import httpx

from zeroone_ops.models.config import GitLabConnectionConfig
from zeroone_ops.providers.gitlab_dashboard_client import GitLabDashboardClient


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
                    "title": "AI Code Ops Work Queue",
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
        title="AI Code Ops Work Queue",
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
                "title": "AI Code Ops Work Queue",
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
        title="AI Code Ops Work Queue",
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
                "title": "AI Code Ops Work Queue",
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


def test_list_issue_notes_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/issues/11/notes"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 77,
                    "body": "/zeroone policy show",
                    "created_at": "2026-04-28T09:00:00.000Z",
                    "author": {"username": "operator"},
                }
            ],
        )

    client = GitLabDashboardClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    notes = client.list_issue_notes(project_id="123", issue_iid=11)

    assert len(notes) == 1
    assert notes[0].id == 77
    assert notes[0].body == "/zeroone policy show"
    assert notes[0].author_username == "operator"
