"""GitHub API client for remediation pull-request publication."""

from __future__ import annotations

from typing import Any

import httpx

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import GitHubConnectionConfig


class GitHubClientError(RuntimeError):
    """Raised when GitHub remediation publication fails."""


class GitHubClient:
    """GitHub REST client for remediation pull-request publication."""

    def __init__(
        self,
        config: GitHubConnectionConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the GitHub client."""
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

    def find_open_pull_request(
        self,
        *,
        repository_id: str,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequestInfo | None:
        """Return an open pull request for a source/base branch pair when present."""
        owner, _repo = _split_repository_id(repository_id)
        response = self._http_client.get(
            _repository_path(repository_id, "pulls"),
            params={
                "state": "open",
                "head": f"{owner}:{source_branch}",
                "base": target_branch,
                "per_page": 100,
            },
        )
        payload = _parse_list_response(
            response,
            error_message="Unexpected GitHub pull request list payload.",
        )
        for item in payload:
            if not isinstance(item, dict):
                continue
            return _normalize_pull_request_info(item)
        return None

    def create_pull_request(
        self,
        *,
        repository_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> ChangeRequestInfo:
        """Create one GitHub pull request."""
        response = self._http_client.post(
            _repository_path(repository_id, "pulls"),
            json={
                "title": title,
                "body": description,
                "head": source_branch,
                "base": target_branch,
            },
        )
        payload = _parse_dict_response(
            response,
            error_message="Unexpected GitHub pull request payload.",
        )
        return _normalize_pull_request_info(payload)

    def add_issue_labels(
        self,
        *,
        repository_id: str,
        issue_number: int,
        labels: list[str],
    ) -> None:
        """Apply labels to a pull request through the issue labels endpoint."""
        if not labels:
            return
        response = self._http_client.post(
            _repository_path(repository_id, f"issues/{issue_number}/labels"),
            json={"labels": labels},
        )
        _parse_list_response(response, error_message="Unexpected GitHub issue labels payload.")

    def assign_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
        assignee_username: str,
    ) -> None:
        """Assign a pull request through the issue assignees endpoint."""
        response = self._http_client.post(
            _repository_path(repository_id, f"issues/{issue_number}/assignees"),
            json={"assignees": [assignee_username]},
        )
        _parse_dict_response(response, error_message="Unexpected GitHub issue assignee payload.")


def _repository_path(repository_id: str, suffix: str) -> str:
    """Build one repository-scoped request path without discarding the base URL path."""
    return f"repos/{repository_id}/{suffix}"


def _split_repository_id(repository_id: str) -> tuple[str, str]:
    """Split ``owner/name`` repository IDs."""
    owner, separator, repo = repository_id.partition("/")
    if separator == "" or owner == "" or repo == "":
        raise GitHubClientError("GitHub repository must be in owner/name form.")
    return owner, repo


def _normalize_pull_request_info(payload: dict[str, Any]) -> ChangeRequestInfo:
    """Normalize a GitHub pull request payload into shared change-request info."""
    number = payload.get("number")
    web_url = payload.get("html_url")
    title = payload.get("title")
    if not isinstance(number, int):
        raise GitHubClientError("Unexpected GitHub pull request number.")
    if not isinstance(web_url, str):
        raise GitHubClientError("Unexpected GitHub pull request URL.")
    if not isinstance(title, str):
        raise GitHubClientError("Unexpected GitHub pull request title.")
    return ChangeRequestInfo(iid=number, web_url=web_url, title=title)


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
