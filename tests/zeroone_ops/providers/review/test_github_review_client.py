import json

import httpx
import pytest

from zeroone_ops.models.change_request import ChangeRequestState
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


@pytest.mark.parametrize(
    "api_url,graphql_url",
    [
        ("https://api.github.com", "https://api.github.com/graphql"),
        ("https://git.example.com/api/v3/", "https://git.example.com/api/graphql"),
    ],
)
def test_installation_token_resolves_authenticated_graphql_viewer(api_url, graphql_url) -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        if request.method == "GET":
            assert request.url.path.endswith("/user")
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        assert str(request.url) == graphql_url
        assert json.loads(request.content) == {"query": "query { viewer { login } }"}
        return httpx.Response(200, json={"data": {"viewer": {"login": "installation-bot[bot]"}}})

    client = GitHubReviewClient(
        GitHubConnectionConfig(
            api_url=api_url,
            server_url="https://git.example.com",
            token="dummy-installation-token",
            repository="org/repo",
        ),
        http_client=httpx.Client(transport=httpx.MockTransport(handler), base_url=api_url),
    )

    assert client.get_current_user_username() == "installation-bot[bot]"
    assert len(calls) == 2
    assert calls[-1] == ("POST", graphql_url)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": None},
        {"data": {"viewer": None}},
        {"data": {"viewer": {"login": None}}},
        {"data": {"viewer": {"login": ""}}},
        {"data": {"viewer": {"login": " "}}},
        {"errors": [{"message": "unavailable"}]},
        {"errors": [{"message": "partial"}], "data": {"viewer": {"login": "unverified"}}},
        [],
    ],
)
def test_installation_viewer_requires_complete_verified_identity(payload) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        assert request.url.path == "/graphql"
        return httpx.Response(200, json=payload)

    with pytest.raises(ReviewPlatformClientError):
        build_client(handler).get_current_user_username()
    assert calls == ["GET", "POST"]


@pytest.mark.parametrize("status", [401, 404, 429, 500])
def test_user_operational_failures_do_not_trigger_graphql_fallback(status: int) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        assert request.method == "GET" and request.url.path == "/user"
        return httpx.Response(status, json={"message": "unavailable"})

    with pytest.raises(ReviewPlatformClientError):
        build_client(handler).get_current_user_username()
    assert calls == ["GET"]


@pytest.mark.parametrize("failure", ["http", "timeout", "invalid_json"])
def test_installation_viewer_transport_errors_remain_failures(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        assert request.url.path == "/graphql"
        if failure == "timeout":
            raise httpx.ReadTimeout("Viewer lookup unavailable", request=request)
        if failure == "http":
            return httpx.Response(403, json={"message": "GraphQL forbidden"})
        return httpx.Response(200, text="invalid JSON")

    expected = httpx.ReadTimeout if failure == "timeout" else ReviewPlatformClientError
    with pytest.raises(expected):
        build_client(handler).get_current_user_username()


@pytest.mark.parametrize(
    ("state", "merged_at", "expected_state"),
    [
        ("open", None, "opened"),
        ("closed", None, "closed"),
        ("closed", "2026-06-18T10:00:00Z", "merged"),
    ],
)
def test_get_change_request_state_does_not_fetch_changed_files(
    state: str,
    merged_at: str | None,
    expected_state: str,
) -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/repos/octo-org/octo-repo/pulls/17"
        requests.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "number": 17,
                "html_url": "https://github.com/octo-org/octo-repo/pull/17",
                "head": {"ref": "feature/review", "sha": "abc123"},
                "state": state,
                "merged_at": merged_at,
            },
        )

    result = build_client(handler).get_change_request_state(
        repository_id="octo-org/octo-repo",
        change_request_number=17,
    )

    assert len(requests) == 1
    assert result == ChangeRequestState(
        iid=17,
        web_url="https://github.com/octo-org/octo-repo/pull/17",
        source_branch="feature/review",
        head_sha="abc123",
        state=expected_state,
    )


@pytest.mark.parametrize(
    ("status", "payload"),
    [(404, {"message": "Not Found"}), (200, []), (200, {"number": 17})],
)
def test_get_change_request_state_surfaces_provider_errors(status: int, payload: object) -> None:
    client = build_client(lambda request: httpx.Response(status, json=payload))

    with pytest.raises(ReviewPlatformClientError):
        client.get_change_request_state(
            repository_id="octo-org/octo-repo",
            change_request_number=17,
        )


def test_list_change_request_comments_reads_all_pages() -> None:
    seen_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/repos/octo-org/octo-repo/issues/17/comments"
        assert request.url.params["per_page"] == "100"
        page = request.url.params["page"]
        seen_pages.append(page)
        headers = {}
        if page == "1":
            headers["Link"] = (
                "<https://api.github.com/repos/octo-org/octo-repo/issues/17/comments"
                '?page=2&per_page=100>; rel="next"'
            )
        return httpx.Response(
            200,
            headers=headers,
            json=[
                {
                    "id": int(page),
                    "body": f"Review {page}",
                    "user": {"login": "zeroone-ops[bot]"},
                }
            ],
        )

    comments = build_client(handler).list_change_request_comments(
        repository_id="octo-org/octo-repo",
        change_request_number=17,
    )

    assert seen_pages == ["1", "2"]
    assert [comment.id for comment in comments] == [1, 2]
    assert [comment.body for comment in comments] == ["Review 1", "Review 2"]


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
