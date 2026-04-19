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
                "web_url": ("https://gitlab.example.com/group/project/-/merge_requests/17#note_55"),
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


def test_create_merge_request_note_allows_missing_web_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests/17/notes"
        assert request.method == "POST"
        return httpx.Response(
            201,
            json={
                "id": 56,
                "body": "summary",
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

    assert note.id == 56
    assert note.web_url is None


def test_list_merge_request_notes_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests/17/notes"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json=[
                {
                    "id": 55,
                    "body": "note body",
                    "web_url": "https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
                    "created_at": "2026-04-19T11:27:42.046Z",
                    "author": {"username": "ai-sonar-bot"},
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

    notes = client.list_merge_request_notes(project_id="123", merge_request_iid=17)

    assert len(notes) == 1
    assert notes[0].id == 55
    assert notes[0].body == "note body"
    assert notes[0].author_username == "ai-sonar-bot"
    assert notes[0].created_at == "2026-04-19T11:27:42.046Z"


def test_list_merge_request_notes_paginates_until_gitlab_history_is_exhausted() -> None:
    seen_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests/17/notes"
        assert request.method == "GET"
        seen_pages.append(request.url.params["page"])
        assert request.url.params["per_page"] == "100"
        if request.url.params["page"] == "1":
            return httpx.Response(
                200,
                headers={"X-Next-Page": "2"},
                json=[
                    {
                        "id": 55,
                        "body": "note body 1",
                        "web_url": "https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
                        "created_at": "2026-04-19T11:27:42.046Z",
                        "author": {"username": "ai-sonar-bot"},
                    }
                ],
            )
        return httpx.Response(
            200,
            headers={"X-Next-Page": ""},
            json=[
                {
                    "id": 56,
                    "body": "note body 2",
                    "web_url": "https://gitlab.example.com/group/project/-/merge_requests/17#note_56",
                    "created_at": "2026-04-19T11:28:42.046Z",
                    "author": {"username": "ai-sonar-bot"},
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

    notes = client.list_merge_request_notes(project_id="123", merge_request_iid=17)

    assert seen_pages == ["1", "2"]
    assert [note.id for note in notes] == [55, 56]


def test_get_merge_request_state_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/projects/123/merge_requests/17"
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "iid": 17,
                "web_url": "https://gitlab.example.com/group/project/-/merge_requests/17",
                "source_branch": "feature/review",
                "sha": "abc123",
                "state": "merged",
            },
        )

    client = GitLabReviewClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    merge_request = client.get_merge_request_state(project_id="123", merge_request_iid=17)

    assert merge_request.iid == 17
    assert merge_request.source_branch == "feature/review"
    assert merge_request.head_sha == "abc123"
    assert merge_request.state == "merged"


def test_get_current_user_username_normalizes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/user"
        assert request.method == "GET"
        return httpx.Response(200, json={"username": "custom-bot-user"})

    client = GitLabReviewClient(
        build_config(),
        http_client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://gitlab.example.com",
        ),
    )

    username = client.get_current_user_username()

    assert username == "custom-bot-user"
