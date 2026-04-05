from __future__ import annotations

import httpx

from ai_sonar_bot.models.config import GitLabConnectionConfig
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient


def build_config() -> GitLabConnectionConfig:
    return GitLabConnectionConfig(
        url="https://gitlab.example.com",
        token="token",
        project_id="123",
    )


def test_list_open_merge_requests_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests"
        assert request.method == "GET"
        assert request.url.params["state"] == "opened"
        return httpx.Response(
            200,
            json=[
                {
                    "iid": 17,
                    "title": "feat: refactor review flow",
                    "description": "summary",
                    "source_branch": "feature/review",
                    "target_branch": "main",
                    "web_url": "https://gitlab.example.com/group/project/-/merge_requests/17",
                    "sha": "abc123",
                    "draft": False,
                    "author": {"username": "justin"},
                }
            ],
        )

    client = GitLabReviewClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    merge_requests = client.list_open_merge_requests(project_id="123")

    assert len(merge_requests) == 1
    assert merge_requests[0].iid == 17
    assert merge_requests[0].head_sha == "abc123"
    assert merge_requests[0].author_username == "justin"
    assert merge_requests[0].changes == []


def test_get_merge_request_normalizes_changes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests/17/changes"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "iid": 17,
                "title": "feat: refactor review flow",
                "description": "summary",
                "source_branch": "feature/review",
                "target_branch": "main",
                "web_url": "https://gitlab.example.com/group/project/-/merge_requests/17",
                "sha": "abc123",
                "draft": False,
                "author": {"username": "justin"},
                "changes": [
                    {
                        "old_path": "src/old.py",
                        "new_path": "src/new.py",
                        "diff": "@@ -1 +1 @@\n-old\n+new\n",
                        "deleted_file": False,
                        "new_file": False,
                        "renamed_file": True,
                    }
                ],
            },
        )

    client = GitLabReviewClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    merge_request = client.get_merge_request(project_id="123", merge_request_iid=17)

    assert merge_request.iid == 17
    assert len(merge_request.changes) == 1
    assert merge_request.changes[0].new_path == "src/new.py"
    assert merge_request.changes[0].renamed_file is True


def test_create_merge_request_note_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests/17/notes"
        assert request.method == "POST"
        return httpx.Response(
            201,
            json={
                "id": 55,
                "web_url": (
                    "https://gitlab.example.com/group/project/-/merge_requests/17"
                    "#note_55"
                ),
            },
        )

    client = GitLabReviewClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    note = client.create_merge_request_note(project_id="123", merge_request_iid=17, body="summary")

    assert note.id == 55
    assert note.web_url.endswith("#note_55")
