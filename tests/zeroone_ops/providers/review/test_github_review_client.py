import json

import httpx
import pytest

from zeroone_ops.models.config import GitHubConnectionConfig
from zeroone_ops.providers.review.github import GitHubReviewClient
from zeroone_ops.providers.review.platform import ReviewPlatformClientError


def build_client(handler) -> GitHubReviewClient:  # noqa: ANN001, ANN202
    http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.github.com",
    )
    return GitHubReviewClient(
        GitHubConnectionConfig(
            api_url="https://api.github.com",
            server_url="https://github.com",
            token="github-token",
            repository="octo-org/octo-repo",
        ),
        http_client=http_client,
    )


def test_get_change_request_fetches_pull_request_and_files() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octo-org/octo-repo/pulls/17":
            return httpx.Response(
                200,
                json={
                    "number": 17,
                    "title": "feat: review flow",
                    "body": "summary",
                    "html_url": "https://github.com/octo-org/octo-repo/pull/17",
                    "draft": False,
                    "user": {"login": "octocat"},
                    "head": {"ref": "feature/review", "sha": "abc123"},
                    "base": {"ref": "main", "sha": "def456"},
                },
            )
        if request.url.path == "/repos/octo-org/octo-repo/pulls/17/files":
            return httpx.Response(
                200,
                json=[
                    {
                        "filename": "src/service.py",
                        "previous_filename": None,
                        "patch": "@@ -1,1 +1,1 @@\n-value = 1\n+value = 2\n",
                        "status": "modified",
                    }
                ],
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = build_client(handler)

    change_request = client.get_change_request(
        repository_id="octo-org/octo-repo",
        change_request_number=17,
    )

    assert change_request.change_request_number == 17
    assert change_request.title == "feat: review flow"
    assert change_request.web_url == "https://github.com/octo-org/octo-repo/pull/17"
    assert change_request.source_branch == "feature/review"
    assert change_request.target_branch == "main"
    assert change_request.head_sha == "abc123"
    assert change_request.author_username == "octocat"
    assert change_request.diff_refs is not None
    assert change_request.diff_refs.base_sha == "def456"
    assert change_request.diff_refs.start_sha == "def456"
    assert change_request.diff_refs.head_sha == "abc123"
    assert len(change_request.changes) == 1
    assert change_request.changes[0].new_path == "src/service.py"
    assert change_request.changes[0].old_path == "src/service.py"


def test_list_create_and_update_change_request_comments() -> None:
    observed_bodies: list[str] = []
    comments_path = "/repos/octo-org/octo-repo/issues/17/comments"
    single_comment_path = "/repos/octo-org/octo-repo/issues/comments/52"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == comments_path:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 51,
                        "html_url": "https://github.com/octo-org/octo-repo/pull/17#issuecomment-51",
                        "body": "Earlier review summary",
                        "user": {"login": "zeroone-ops[bot]"},
                        "created_at": "2026-06-18T10:00:00Z",
                    }
                ],
            )
        if request.method == "POST" and request.url.path == comments_path:
            observed_bodies.append(json.loads(request.content.decode("utf-8"))["body"])
            return httpx.Response(
                201,
                json={
                    "id": 52,
                    "html_url": "https://github.com/octo-org/octo-repo/pull/17#issuecomment-52",
                    "body": observed_bodies[-1],
                    "user": {"login": "zeroone-ops[bot]"},
                    "created_at": "2026-06-18T10:05:00Z",
                },
            )
        if request.method == "PATCH" and request.url.path == single_comment_path:
            observed_bodies.append(json.loads(request.content.decode("utf-8"))["body"])
            return httpx.Response(
                200,
                json={
                    "id": 52,
                    "html_url": "https://github.com/octo-org/octo-repo/pull/17#issuecomment-52",
                    "body": observed_bodies[-1],
                    "user": {"login": "zeroone-ops[bot]"},
                    "created_at": "2026-06-18T10:05:00Z",
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = build_client(handler)

    comments = client.list_change_request_comments(
        repository_id="octo-org/octo-repo",
        change_request_number=17,
    )
    created = client.create_change_request_comment(
        repository_id="octo-org/octo-repo",
        change_request_number=17,
        body="New review summary",
    )
    updated = client.update_change_request_comment(
        repository_id="octo-org/octo-repo",
        change_request_number=17,
        note_id=52,
        body="Updated review summary",
    )

    assert len(comments) == 1
    assert comments[0].id == 51
    assert comments[0].author_username == "zeroone-ops[bot]"
    assert created.body == "New review summary"
    assert updated.body == "Updated review summary"
    assert observed_bodies == ["New review summary", "Updated review summary"]


def test_get_current_user_username_reads_login() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "zeroone-ops[bot]"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = build_client(handler)

    assert client.get_current_user_username() == "zeroone-ops[bot]"


def test_create_change_request_inline_comment_posts_single_line_right_comment() -> None:
    observed_payloads: list[dict[str, object]] = []
    comments_path = "/repos/octo-org/octo-repo/pulls/17/comments"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == comments_path:
            observed_payloads.append(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                201,
                json={
                    "id": 61,
                    "html_url": ("https://github.com/octo-org/octo-repo/pull/17#discussion_r61"),
                    "body": "Inline finding",
                    "user": {"login": "zeroone-ops[bot]"},
                    "created_at": "2026-06-21T09:00:00Z",
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = build_client(handler)

    comment = client.create_change_request_inline_comment(
        repository_id="octo-org/octo-repo",
        change_request_number=17,
        body="Inline finding",
        base_sha="base123",
        start_sha="start123",
        head_sha="head123",
        old_path="src/old_service.py",
        new_path="src/service.py",
        new_line=12,
    )

    assert comment.id == 61
    assert comment.author_username == "zeroone-ops[bot]"
    assert observed_payloads == [
        {
            "body": "Inline finding",
            "commit_id": "head123",
            "path": "src/service.py",
            "line": 12,
            "side": "RIGHT",
        }
    ]


def test_create_change_request_inline_comment_surfaces_provider_errors() -> None:
    comments_path = "/repos/octo-org/octo-repo/pulls/17/comments"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == comments_path:
            return httpx.Response(422, json={"message": "Validation Failed"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = build_client(handler)

    with pytest.raises(ReviewPlatformClientError) as exc_info:
        client.create_change_request_inline_comment(
            repository_id="octo-org/octo-repo",
            change_request_number=17,
            body="Inline finding",
            base_sha="base123",
            start_sha="start123",
            head_sha="head123",
            old_path="src/service.py",
            new_path="src/service.py",
            new_line=12,
        )

    assert "422" in str(exc_info.value)
