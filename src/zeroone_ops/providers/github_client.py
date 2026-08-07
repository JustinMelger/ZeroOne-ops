"""GitHub API client for remediation pull-request publication."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from zeroone_ops.models.change_request import ChangeRequestInfo, ChangeRequestState
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

    def get_branch_head_sha(
        self,
        *,
        repository_id: str,
        branch_name: str,
    ) -> str | None:
        """Return the remote branch head SHA, or ``None`` when the branch is absent."""
        response = self._http_client.get(
            _repository_path(
                repository_id,
                f"git/ref/heads/{_encode_branch_reference(branch_name)}",
            )
        )
        if response.status_code == 404:
            return None
        payload = _parse_dict_response(
            response,
            error_message="Unexpected GitHub branch reference payload.",
        )
        reference = payload.get("object")
        if not isinstance(reference, dict):
            raise GitHubClientError("Unexpected GitHub branch reference object.")
        sha = reference.get("sha")
        if not isinstance(sha, str):
            raise GitHubClientError("Unexpected GitHub branch reference SHA.")
        return sha

    def get_change_request_state(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> ChangeRequestState:
        """Fetch one GitHub pull-request state using provider-neutral naming."""
        return self.get_pull_request_state(
            repository_id=repository_id,
            pull_request_number=change_request_number,
        )

    def get_pull_request_state(
        self,
        *,
        repository_id: str,
        pull_request_number: int,
    ) -> ChangeRequestState:
        """Fetch one GitHub pull-request state for reconciliation."""
        response = self._http_client.get(
            _repository_path(repository_id, f"pulls/{pull_request_number}")
        )
        payload = _parse_dict_response(
            response,
            error_message="Unexpected GitHub pull request state payload.",
        )
        return _normalize_pull_request_state(payload)

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


def _encode_branch_reference(branch_name: str) -> str:
    """Encode one branch reference while preserving slash-separated branch names."""
    return quote(branch_name, safe="/")


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


def _normalize_pull_request_state(payload: dict[str, Any]) -> ChangeRequestState:
    """Normalize one GitHub pull-request payload into shared reconciliation state."""
    number = payload.get("number")
    web_url = payload.get("html_url")
    state = payload.get("state")
    merged_at = payload.get("merged_at")
    head = payload.get("head")
    if not isinstance(number, int):
        raise GitHubClientError("Unexpected GitHub pull request number.")
    if not isinstance(web_url, str):
        raise GitHubClientError("Unexpected GitHub pull request URL.")
    if not isinstance(state, str):
        raise GitHubClientError("Unexpected GitHub pull request state.")
    if not isinstance(head, dict):
        raise GitHubClientError("Unexpected GitHub pull request head payload.")
    source_branch = head.get("ref")
    head_sha = head.get("sha")
    if not isinstance(source_branch, str):
        raise GitHubClientError("Unexpected GitHub pull request source branch.")
    if not isinstance(head_sha, str):
        raise GitHubClientError("Unexpected GitHub pull request head SHA.")
    normalized_state = (
        "merged" if merged_at is not None else ("opened" if state == "open" else state)
    )
    return ChangeRequestState(
        iid=number,
        web_url=web_url,
        source_branch=source_branch,
        head_sha=head_sha,
        state=normalized_state,
    )


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
