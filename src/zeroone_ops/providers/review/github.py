"""GitHub review API client."""

from __future__ import annotations

from typing import Any

import httpx

from zeroone_ops.models.config import GitHubConnectionConfig
from zeroone_ops.models.review import (
    ChangeRequestChangedFile,
    ChangeRequestDiffRefs,
    ChangeRequestReviewCandidate,
    InlineCommentStatus,
    ReviewComment,
)
from zeroone_ops.providers.review.platform import ReviewPlatformClientError


class GitHubReviewClient:
    """GitHub REST client for pull-request review workflows."""

    def __init__(
        self,
        config: GitHubConnectionConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the GitHub review client."""
        self.config = config
        self._http_client = http_client or httpx.Client(
            base_url=config.api_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {config.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def get_change_request(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> ChangeRequestReviewCandidate:
        """Fetch one GitHub pull request plus changed files."""
        pull_request = self._get_json(
            f"/repos/{repository_id}/pulls/{change_request_number}",
            error_message="Unexpected GitHub pull request payload.",
        )
        files = self._list_paginated_json(
            f"/repos/{repository_id}/pulls/{change_request_number}/files",
            error_message="Unexpected GitHub pull request files payload.",
        )
        return _normalize_pull_request(pull_request, files)

    def list_change_request_comments(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> list[ReviewComment]:
        """List GitHub issue comments for one pull request."""
        items = self._list_paginated_json(
            f"/repos/{repository_id}/issues/{change_request_number}/comments",
            error_message="Unexpected GitHub issue comments payload.",
        )
        return [_normalize_issue_comment(item) for item in items]

    def create_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
    ) -> ReviewComment:
        """Publish one authoritative GitHub pull-request issue comment."""
        payload = self._post_json(
            f"/repos/{repository_id}/issues/{change_request_number}/comments",
            json={"body": body},
            error_message="Unexpected GitHub issue comment payload.",
        )
        return _normalize_issue_comment(payload)

    def update_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        note_id: int,
        body: str,
    ) -> ReviewComment:
        """Update one authoritative GitHub pull-request issue comment."""
        del change_request_number
        payload = self._patch_json(
            f"/repos/{repository_id}/issues/comments/{note_id}",
            json={"body": body},
            error_message="Unexpected GitHub issue comment update payload.",
        )
        return _normalize_issue_comment(payload)

    def create_change_request_inline_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        old_path: str,
        new_path: str,
        new_line: int,
    ) -> ReviewComment:
        """Publish one single-line inline pull-request review comment on the new diff side."""
        del base_sha, start_sha, old_path
        payload = self._post_json(
            f"/repos/{repository_id}/pulls/{change_request_number}/comments",
            json={
                "body": body,
                "commit_id": head_sha,
                "path": new_path,
                "line": new_line,
                "side": "RIGHT",
            },
            error_message="Unexpected GitHub pull request review comment payload.",
        )
        return _normalize_review_comment(payload)

    def get_current_user_username(self) -> str:
        """Return the GitHub login associated with the active API token."""
        payload = self._get_json(
            "/user",
            error_message="Unexpected GitHub current user payload.",
        )
        login = payload.get("login")
        if not isinstance(login, str):
            raise ReviewPlatformClientError("Unexpected GitHub current user login.")
        return login

    def allows_machine_safe_comment_fallback(self) -> bool:
        """Allow machine-safe continuity fallback when author lookup is unavailable."""
        return True

    def list_change_request_inline_comment_statuses(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        comment_ids: list[str],
    ) -> dict[str, InlineCommentStatus]:
        """Return provider-observed inline-thread states for known inline comment IDs."""
        if not comment_ids:
            return {}
        owner, name = _split_repository_id(repository_id)
        payload = self._post_json(
            "/graphql",
            json={
                "query": _inline_comment_thread_status_query(),
                "variables": {
                    "owner": owner,
                    "name": name,
                    "number": change_request_number,
                },
            },
            error_message="Unexpected GitHub pull request review thread payload.",
        )
        return _extract_inline_comment_statuses(payload, comment_ids)

    def _get_json(
        self,
        path: str,
        *,
        error_message: str,
    ) -> dict[str, Any]:
        response = self._http_client.get(path)
        return _parse_dict_response(
            response,
            error_message=error_message,
        )

    def _post_json(
        self,
        path: str,
        *,
        json: dict[str, object],
        error_message: str,
    ) -> dict[str, Any]:
        response = self._http_client.post(path, json=json)
        return _parse_dict_response(response, error_message=error_message)

    def _patch_json(
        self,
        path: str,
        *,
        json: dict[str, object],
        error_message: str,
    ) -> dict[str, Any]:
        response = self._http_client.patch(path, json=json)
        return _parse_dict_response(response, error_message=error_message)

    def _list_paginated_json(self, path: str, *, error_message: str) -> list[dict[str, Any]]:
        page = 1
        items: list[dict[str, Any]] = []
        while True:
            response = self._http_client.get(path, params={"page": page, "per_page": 100})
            payload = _parse_list_response(response, error_message=error_message)
            items.extend(item for item in payload if isinstance(item, dict))
            next_link = response.links.get("next")
            if not next_link:
                break
            page += 1
        return items


def _parse_dict_response(
    response: httpx.Response,
    *,
    error_message: str,
) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise ReviewPlatformClientError(str(error)) from error
    try:
        payload = response.json()
    except ValueError as error:
        raise ReviewPlatformClientError(error_message) from error
    if not isinstance(payload, dict):
        raise ReviewPlatformClientError(error_message)
    return payload


def _parse_list_response(
    response: httpx.Response,
    *,
    error_message: str,
) -> list[Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise ReviewPlatformClientError(str(error)) from error
    try:
        payload = response.json()
    except ValueError as error:
        raise ReviewPlatformClientError(error_message) from error
    if not isinstance(payload, list):
        raise ReviewPlatformClientError(error_message)
    return payload


def _normalize_pull_request(
    payload: dict[str, Any],
    files: list[dict[str, Any]],
) -> ChangeRequestReviewCandidate:
    number = payload.get("number")
    title = payload.get("title")
    body = payload.get("body")
    html_url = payload.get("html_url")
    draft = payload.get("draft", False)
    head = payload.get("head")
    base = payload.get("base")
    user = payload.get("user")

    if not isinstance(number, int) or not isinstance(title, str):
        raise ReviewPlatformClientError("Unexpected GitHub pull request structure.")
    if body is not None and not isinstance(body, str):
        raise ReviewPlatformClientError("Unexpected GitHub pull request body.")
    if not isinstance(html_url, str):
        raise ReviewPlatformClientError("Unexpected GitHub pull request link structure.")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise ReviewPlatformClientError("Unexpected GitHub pull request branch structure.")

    head_ref = head.get("ref")
    head_sha = head.get("sha")
    base_ref = base.get("ref")
    base_sha = base.get("sha")
    if (
        not isinstance(head_ref, str)
        or not isinstance(head_sha, str)
        or not isinstance(base_ref, str)
        or not isinstance(base_sha, str)
    ):
        raise ReviewPlatformClientError("Unexpected GitHub pull request head/base structure.")

    author_username = None
    if isinstance(user, dict):
        login = user.get("login")
        if login is not None and not isinstance(login, str):
            raise ReviewPlatformClientError("Unexpected GitHub pull request author structure.")
        author_username = login

    return ChangeRequestReviewCandidate(
        change_request_number=number,
        title=title,
        description=body,
        source_branch=head_ref,
        target_branch=base_ref,
        web_url=html_url,
        head_sha=head_sha,
        draft=bool(draft),
        author_username=author_username,
        diff_refs=ChangeRequestDiffRefs(
            base_sha=base_sha,
            start_sha=base_sha,
            head_sha=head_sha,
        ),
        changes=[_normalize_pull_request_file(item) for item in files],
    )


def _normalize_pull_request_file(payload: dict[str, Any]) -> ChangeRequestChangedFile:
    filename = payload.get("filename")
    previous_filename = payload.get("previous_filename")
    patch = payload.get("patch")
    status = payload.get("status")

    if not isinstance(filename, str):
        raise ReviewPlatformClientError("Unexpected GitHub pull request file payload.")
    if previous_filename is not None and not isinstance(previous_filename, str):
        raise ReviewPlatformClientError("Unexpected GitHub pull request previous filename.")
    if patch is not None and not isinstance(patch, str):
        patch = None
    if status is not None and not isinstance(status, str):
        raise ReviewPlatformClientError("Unexpected GitHub pull request file status.")

    old_path = previous_filename or filename
    new_path = filename
    return ChangeRequestChangedFile(
        old_path=old_path,
        new_path=new_path,
        diff=patch,
        deleted_file=status == "removed",
        new_file=status == "added",
        renamed_file=status == "renamed",
    )


def _normalize_issue_comment(payload: dict[str, Any]) -> ReviewComment:
    comment_id = payload.get("id")
    html_url = payload.get("html_url")
    body = payload.get("body")
    created_at = payload.get("created_at")
    user = payload.get("user")

    if not isinstance(comment_id, int):
        raise ReviewPlatformClientError("Unexpected GitHub issue comment identifier.")
    if html_url is not None and not isinstance(html_url, str):
        raise ReviewPlatformClientError("Unexpected GitHub issue comment URL.")
    if body is not None and not isinstance(body, str):
        raise ReviewPlatformClientError("Unexpected GitHub issue comment body.")
    if created_at is not None and not isinstance(created_at, str):
        raise ReviewPlatformClientError("Unexpected GitHub issue comment timestamp.")

    author_username = None
    if isinstance(user, dict):
        login = user.get("login")
        if login is not None and not isinstance(login, str):
            raise ReviewPlatformClientError("Unexpected GitHub issue comment author.")
        author_username = login

    return ReviewComment(
        id=comment_id,
        web_url=html_url,
        body=body,
        author_username=author_username,
        created_at=created_at,
    )


def _normalize_review_comment(payload: dict[str, Any]) -> ReviewComment:
    """Normalize one GitHub pull-request review comment payload."""
    comment_id = payload.get("id")
    html_url = payload.get("html_url")
    body = payload.get("body")
    created_at = payload.get("created_at")
    user = payload.get("user")

    if not isinstance(comment_id, int):
        raise ReviewPlatformClientError("Unexpected GitHub review comment identifier.")
    if html_url is not None and not isinstance(html_url, str):
        raise ReviewPlatformClientError("Unexpected GitHub review comment URL.")
    if body is not None and not isinstance(body, str):
        raise ReviewPlatformClientError("Unexpected GitHub review comment body.")
    if created_at is not None and not isinstance(created_at, str):
        raise ReviewPlatformClientError("Unexpected GitHub review comment timestamp.")

    author_username = None
    if isinstance(user, dict):
        login = user.get("login")
        if login is not None and not isinstance(login, str):
            raise ReviewPlatformClientError("Unexpected GitHub review comment author.")
        author_username = login

    return ReviewComment(
        id=comment_id,
        web_url=html_url,
        body=body,
        author_username=author_username,
        created_at=created_at,
    )


def _inline_comment_thread_status_query() -> str:
    """Return the bounded GraphQL query for inline-thread resolution state."""
    return """
query InlineCommentThreadStates($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        nodes {
          isResolved
          comments(first: 100) {
            nodes {
              databaseId
            }
          }
        }
      }
    }
  }
}
""".strip()


def _split_repository_id(repository_id: str) -> tuple[str, str]:
    """Split one GitHub repository id into owner and name."""
    owner, separator, name = repository_id.partition("/")
    if not owner or not separator or not name:
        raise ReviewPlatformClientError("Unexpected GitHub repository identifier.")
    return owner, name


def _extract_inline_comment_statuses(
    payload: dict[str, Any],
    comment_ids: list[str],
) -> dict[str, InlineCommentStatus]:
    """Extract normalized inline comment states from one GraphQL review-thread payload."""
    expected_ids = set(comment_ids)
    data = payload.get("data")
    repository = data.get("repository") if isinstance(data, dict) else None
    if not isinstance(repository, dict):
        raise ReviewPlatformClientError("Unexpected GitHub review thread repository payload.")
    pull_request = repository.get("pullRequest")
    if not isinstance(pull_request, dict):
        raise ReviewPlatformClientError("Unexpected GitHub review thread pull request payload.")
    review_threads = pull_request.get("reviewThreads")
    if not isinstance(review_threads, dict):
        raise ReviewPlatformClientError("Unexpected GitHub review thread listing payload.")
    nodes = review_threads.get("nodes")
    if not isinstance(nodes, list):
        raise ReviewPlatformClientError("Unexpected GitHub review thread nodes payload.")

    statuses: dict[str, InlineCommentStatus] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        is_resolved = node.get("isResolved")
        if not isinstance(is_resolved, bool):
            raise ReviewPlatformClientError("Unexpected GitHub review thread resolution state.")
        comments = node.get("comments")
        if not isinstance(comments, dict):
            raise ReviewPlatformClientError("Unexpected GitHub review thread comments payload.")
        comment_nodes = comments.get("nodes")
        if not isinstance(comment_nodes, list):
            raise ReviewPlatformClientError(
                "Unexpected GitHub review thread comment nodes payload."
            )
        normalized_status: InlineCommentStatus = "resolved" if is_resolved else "published"
        for comment_node in comment_nodes:
            if not isinstance(comment_node, dict):
                continue
            database_id = comment_node.get("databaseId")
            if database_id is None:
                continue
            if not isinstance(database_id, int):
                raise ReviewPlatformClientError("Unexpected GitHub review comment database id.")
            comment_id = str(database_id)
            if comment_id not in expected_ids:
                continue
            statuses[comment_id] = normalized_status
    return statuses
