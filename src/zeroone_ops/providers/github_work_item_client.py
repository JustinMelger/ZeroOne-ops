"""GitHub issue client for work-item control-plane transport."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import httpx

from zeroone_ops.models.config import GitHubConnectionConfig
from zeroone_ops.models.github import GitHubIssueComment, GitHubIssueInfo
from zeroone_ops.providers.github_client import GitHubClientError


class GitHubWorkItemClient:
    """GitHub REST client for authoritative work-item issues."""

    def __init__(
        self,
        config: GitHubConnectionConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the GitHub work-item client."""
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

    def list_open_issues(
        self,
        *,
        repository_id: str,
        labels: list[str] | None = None,
    ) -> list[GitHubIssueInfo]:
        """List open GitHub issues for one repository and label set."""
        return self.list_issues(
            repository_id=repository_id,
            state="open",
            labels=labels,
        )

    def list_closed_issues(
        self,
        *,
        repository_id: str,
        labels: list[str] | None = None,
    ) -> list[GitHubIssueInfo]:
        """List closed GitHub issues for one repository and label set."""
        return self.list_issues(
            repository_id=repository_id,
            state="closed",
            labels=labels,
        )

    def list_issues(
        self,
        *,
        repository_id: str,
        state: Literal["open", "closed"],
        labels: list[str] | None = None,
    ) -> list[GitHubIssueInfo]:
        """List GitHub issues in one supported state for a repository and label set."""
        page = 1
        issues: list[GitHubIssueInfo] = []
        while True:
            response = self._http_client.get(
                _repository_path(repository_id, "issues"),
                params={
                    "state": state,
                    "labels": ",".join(labels or []),
                    "page": page,
                    "per_page": 100,
                },
            )
            payload = _parse_list_response(
                response,
                error_message="Unexpected GitHub issue list payload.",
            )
            issues.extend(
                _normalize_issue_info(item)
                for item in payload
                if isinstance(item, dict) and item.get("pull_request") is None
            )
            next_link = response.links.get("next")
            if not next_link:
                break
            page += 1
        return issues

    def create_issue(
        self,
        *,
        repository_id: str,
        title: str,
        body: str,
        labels: list[str],
    ) -> GitHubIssueInfo:
        """Create one authoritative GitHub work-item issue."""
        payload = _parse_dict_response(
            self._http_client.post(
                _repository_path(repository_id, "issues"),
                json={
                    "title": title,
                    "body": body,
                    "labels": labels,
                },
            ),
            error_message="Unexpected GitHub work-item issue payload.",
        )
        return _normalize_issue_info(payload)

    def update_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
        title: str,
        body: str,
        labels: list[str],
    ) -> GitHubIssueInfo:
        """Update one authoritative GitHub work-item issue."""
        payload = _parse_dict_response(
            self._http_client.patch(
                _repository_path(repository_id, f"issues/{issue_number}"),
                json={
                    "title": title,
                    "body": body,
                    "labels": labels,
                },
            ),
            error_message="Unexpected GitHub work-item issue update payload.",
        )
        return _normalize_issue_info(payload)

    def close_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
    ) -> GitHubIssueInfo:
        """Close one authoritative GitHub work-item issue."""
        payload = _parse_dict_response(
            self._http_client.patch(
                _repository_path(repository_id, f"issues/{issue_number}"),
                json={"state": "closed"},
            ),
            error_message="Unexpected GitHub work-item issue close payload.",
        )
        return _normalize_issue_info(payload)

    def reopen_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
    ) -> GitHubIssueInfo:
        """Reopen one authoritative GitHub work-item issue."""
        payload = _parse_dict_response(
            self._http_client.patch(
                _repository_path(repository_id, f"issues/{issue_number}"),
                json={"state": "open"},
            ),
            error_message="Unexpected GitHub work-item issue reopen payload.",
        )
        return _normalize_issue_info(payload)

    def list_issue_comments(
        self,
        *,
        repository_id: str,
        issue_number: int,
    ) -> list[GitHubIssueComment]:
        """List every comment for one authoritative work-item issue."""
        page = 1
        comments: list[GitHubIssueComment] = []
        while True:
            response = self._http_client.get(
                _repository_path(repository_id, f"issues/{issue_number}/comments"),
                params={"page": page, "per_page": 100},
            )
            payload = _parse_list_response(
                response,
                error_message="Unexpected GitHub work-item comments payload.",
            )
            comments.extend(
                _normalize_issue_comment(item) for item in payload if isinstance(item, dict)
            )
            if not response.links.get("next"):
                break
            page += 1
        return comments

    def get_repository_permission(
        self,
        *,
        repository_id: str,
        username: str,
    ) -> str:
        """Return the GitHub repository permission for one username."""
        payload = _parse_dict_response(
            self._http_client.get(
                _repository_path(repository_id, f"collaborators/{username}/permission")
            ),
            error_message="Unexpected GitHub collaborator permission payload.",
        )
        permission = payload.get("permission")
        role_name = payload.get("role_name")
        if isinstance(role_name, str) and role_name:
            return role_name
        if isinstance(permission, str) and permission:
            return permission
        raise GitHubClientError("Unexpected GitHub collaborator permission payload.")


def _repository_path(repository_id: str, suffix: str) -> str:
    """Build one repository-scoped request path without discarding the base URL path."""
    return f"repos/{repository_id}/{suffix}"


def _parse_dict_response(
    response: httpx.Response,
    *,
    error_message: str,
) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise GitHubClientError(str(error)) from error
    try:
        payload = response.json()
    except ValueError as error:
        raise GitHubClientError(error_message) from error
    if not isinstance(payload, dict):
        raise GitHubClientError(error_message)
    return payload


def _parse_list_response(
    response: httpx.Response,
    *,
    error_message: str,
) -> list[Any]:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise GitHubClientError(str(error)) from error
    try:
        payload = response.json()
    except ValueError as error:
        raise GitHubClientError(error_message) from error
    if not isinstance(payload, list):
        raise GitHubClientError(error_message)
    return payload


def _normalize_issue_info(payload: dict[str, Any]) -> GitHubIssueInfo:
    """Normalize one GitHub issue payload."""
    issue_id = payload.get("id")
    number = payload.get("number")
    web_url = payload.get("html_url")
    title = payload.get("title")
    body = payload.get("body")
    if not isinstance(issue_id, int):
        raise GitHubClientError("Unexpected GitHub issue identifier.")
    if not isinstance(number, int):
        raise GitHubClientError("Unexpected GitHub issue number.")
    if not isinstance(web_url, str):
        raise GitHubClientError("Unexpected GitHub issue URL.")
    if not isinstance(title, str):
        raise GitHubClientError("Unexpected GitHub issue title.")
    if body is not None and not isinstance(body, str):
        raise GitHubClientError("Unexpected GitHub issue body.")
    return GitHubIssueInfo(
        id=issue_id,
        number=number,
        web_url=web_url,
        title=title,
        body=body or "",
        created_at=_optional_timestamp(payload, key="created_at"),
        updated_at=_optional_timestamp(payload, key="updated_at"),
    )


def _normalize_issue_comment(payload: dict[str, Any]) -> GitHubIssueComment:
    """Normalize one GitHub issue comment payload."""
    comment_id = payload.get("id")
    html_url = payload.get("html_url")
    body = payload.get("body")
    created_at = payload.get("created_at")
    user = payload.get("user")
    if not isinstance(comment_id, int):
        raise GitHubClientError("Unexpected GitHub issue comment identifier.")
    if html_url is not None and not isinstance(html_url, str):
        raise GitHubClientError("Unexpected GitHub issue comment URL.")
    if body is not None and not isinstance(body, str):
        raise GitHubClientError("Unexpected GitHub issue comment body.")
    if created_at is not None and not isinstance(created_at, str):
        raise GitHubClientError("Unexpected GitHub issue comment timestamp.")
    author_username = None
    if isinstance(user, dict):
        login = user.get("login")
        if login is not None and not isinstance(login, str):
            raise GitHubClientError("Unexpected GitHub issue comment author.")
        author_username = login
    return GitHubIssueComment(
        id=comment_id,
        web_url=html_url,
        body=body,
        author_username=author_username,
        created_at=created_at,
    )


def _optional_timestamp(payload: dict[str, Any], *, key: str) -> datetime | None:
    """Return one optional timezone-aware GitHub issue timestamp."""
    field_name = "creation" if key == "created_at" else key
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise GitHubClientError(f"Unexpected GitHub issue {field_name} timestamp.")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GitHubClientError(f"Unexpected GitHub issue {field_name} timestamp.") from error
    if timestamp.tzinfo is None:
        raise GitHubClientError(f"Unexpected GitHub issue {field_name} timestamp.")
    return timestamp
