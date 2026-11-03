"""Verify exact-commit metadata reads through both real review adapters."""

from collections.abc import Callable
from typing import Literal

import httpx
import pytest

from zeroone_ops.models.config import GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.providers.review.github import GitHubReviewClient
from zeroone_ops.providers.review.gitlab import GitLabReviewClient
from zeroone_ops.providers.review.platform import (
    ChangeRequestReviewPlatformProtocol,
    ReviewPlatformClientError,
)

HEAD = "abc1234" + "d" * 33
ORIGIN = "https://provider.example.com"
Platform = Literal["github", "gitlab"]


def _client(platform: Platform, http: httpx.Client) -> ChangeRequestReviewPlatformProtocol:
    if platform == "github":
        return GitHubReviewClient(
            GitHubConnectionConfig(
                api_url=ORIGIN, server_url=ORIGIN, token="offline", repository="acme/shop"
            ),
            http_client=http,
        )
    return GitLabReviewClient(
        GitLabConnectionConfig(url=ORIGIN, token="offline", project_id="acme/shop"),
        http_client=http,
    )


def _read(platform: Platform, handler: Callable[[httpx.Request], httpx.Response]):
    with httpx.Client(base_url=ORIGIN, transport=httpx.MockTransport(handler)) as http:
        return _client(platform, http).get_reviewed_commit(repository_id="acme/shop", head_sha=HEAD)


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    "message,title",
    [
        ("  Fix the bot's identity  \n\nPrivate full message body", "Fix the bot's identity"),
        ("\nDo not promote this second line", None),
        (" \t ", None),
        ("", None),
        (None, None),
        ("x" * 301, "x" * 297 + "..."),
        ("\u6771" * 301, "\u6771" * 297 + "..."),
    ],
)
def test_reads_exact_scoped_commit_and_normalizes_only_first_line(
    platform: Platform, message: str | None, title: str | None
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        expected = (
            f"/repos/acme/shop/git/commits/{HEAD}"
            if platform == "github"
            else f"/api/v4/projects/acme%2Fshop/repository/commits/{HEAD}"
        )
        assert request.url.raw_path.split(b"?")[0] == expected.encode()
        assert dict(request.url.params) == ({} if platform == "github" else {"stats": "false"})
        return httpx.Response(
            200,
            json={
                "sha": HEAD,
                "id": HEAD,
                "message": message,
                "html_url": f"{ORIGIN}/acme/shop/commit/{HEAD}",
                "web_url": f"{ORIGIN}/acme/shop/-/commit/{HEAD}",
            },
        )

    metadata = _read(platform, handler)

    assert len(calls) == 1
    assert metadata.head_sha == HEAD
    assert metadata.title == title
    assert (
        metadata.web_url
        == f"{ORIGIN}/acme/shop/{'-/' if platform == 'gitlab' else ''}commit/{HEAD}"
    )
    assert "Private full message body" not in metadata.model_dump_json()


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    "payload", [[], {}, {"sha": 3, "id": 3}, {"sha": HEAD, "id": HEAD, "message": []}]
)
def test_malformed_payloads_use_neutral_error(platform: Platform, payload: object) -> None:
    with pytest.raises(ReviewPlatformClientError):
        _read(platform, lambda request: httpx.Response(200, json=payload))


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("status", [403, 404, 429, 503])
def test_unavailable_commit_uses_neutral_error(platform: Platform, status: int) -> None:
    with pytest.raises(ReviewPlatformClientError):
        _read(platform, lambda request: httpx.Response(status, json={"message": "unavailable"}))


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_transport_and_invalid_json_use_neutral_error(platform: Platform) -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("offline timeout", request=request)

    with pytest.raises(ReviewPlatformClientError):
        _read(platform, timeout)
    with pytest.raises(ReviewPlatformClientError):
        _read(platform, lambda request: httpx.Response(200, content=b"not JSON"))
