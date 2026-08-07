"""GitLab API client."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus, urlencode

import httpx

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import GitLabConnectionConfig


class GitLabClientError(RuntimeError):
    """Raised when GitLab communication fails."""


class GitLabClient:
    """GitLab REST client."""

    def __init__(
        self,
        config: GitLabConnectionConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the GitLab client.

        Args:
            config: GitLab connection settings.
            http_client: Optional injected HTTP client for testing.
        """
        self.config = config
        self._http_client = http_client or httpx.Client(
            base_url=str(config.url).rstrip("/"),
            headers={"PRIVATE-TOKEN": config.token},
            timeout=30.0,
        )

    def find_open_merge_request(
        self,
        *,
        project_id: str,
        source_branch: str,
        target_branch: str,
    ) -> ChangeRequestInfo | None:
        """Find an existing open merge request for a branch pair."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.get(
            f"/api/v4/projects/{encoded_project_id}/merge_requests",
            params={
                "state": "opened",
                "source_branch": source_branch,
                "target_branch": target_branch,
            },
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, list) or not payload:
            return None
        first = payload[0]
        if not isinstance(first, dict):
            return None
        return _normalize_merge_request(first)

    def create_merge_request(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str] | None = None,
        assignee_id: int | None = None,
    ) -> ChangeRequestInfo:
        """Create a merge request in GitLab."""
        encoded_project_id = quote_plus(project_id)
        request_data: list[tuple[str, str]] = [
            ("source_branch", source_branch),
            ("target_branch", target_branch),
            ("title", title),
            ("description", description),
            ("labels", ",".join(labels or [])),
            ("remove_source_branch", "true"),
        ]
        if assignee_id is not None:
            request_data.append(("assignee_ids[]", str(assignee_id)))
        response = self._http_client.post(
            f"/api/v4/projects/{encoded_project_id}/merge_requests",
            content=_encode_form_data(request_data),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response_payload = _parse_json_response(response)
        if not isinstance(response_payload, dict):
            raise GitLabClientError("Unexpected GitLab response payload.")
        return _normalize_merge_request(response_payload)

    def get_branch_head_sha(
        self,
        *,
        project_id: str,
        branch_name: str,
    ) -> str | None:
        """Return the remote branch head SHA, or ``None`` when the branch is absent."""
        encoded_project_id = quote_plus(project_id)
        encoded_branch_name = quote_plus(branch_name, safe="")
        response = self._http_client.get(
            f"/api/v4/projects/{encoded_project_id}/repository/branches/{encoded_branch_name}"
        )
        if response.status_code == 404:
            return None
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab branch response payload.")
        commit = payload.get("commit")
        if not isinstance(commit, dict):
            raise GitLabClientError("Unexpected GitLab branch commit payload.")
        sha = commit.get("id")
        if not isinstance(sha, str):
            raise GitLabClientError("Unexpected GitLab branch commit SHA.")
        return sha

    def update_merge_request_assignee(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        assignee_id: int,
    ) -> None:
        """Assign an existing merge request to a user."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.put(
            f"/api/v4/projects/{encoded_project_id}/merge_requests/{merge_request_iid}",
            content=_encode_form_data([("assignee_ids[]", str(assignee_id))]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        _parse_json_response(response)

    def find_user_id_by_username(self, username: str) -> int:
        """Resolve a GitLab user id from an exact username lookup."""
        response = self._http_client.get(
            "/api/v4/users",
            params={"username": username},
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, list):
            raise GitLabClientError("Unexpected GitLab users response payload.")
        if not payload:
            raise GitLabClientError(f"GitLab user '{username}' was not found.")
        first = payload[0]
        if not isinstance(first, dict):
            raise GitLabClientError("Unexpected GitLab user structure.")
        user_id = first.get("id")
        if not isinstance(user_id, int):
            raise GitLabClientError("Unexpected GitLab user id structure.")
        return user_id


def _parse_json_response(response: httpx.Response) -> dict[str, Any] | list[Any]:
    """Validate and parse a GitLab JSON response."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        status_code = error.response.status_code
        if status_code == 401:
            message = (
                "GitLab request failed with status 401. The GitLab token is invalid or expired."
            )
        elif status_code == 403:
            message = (
                "GitLab request failed with status 403. "
                "The GitLab token does not have permission for this action."
            )
        else:
            message = f"GitLab request failed with status {status_code}."
        raise GitLabClientError(message) from error

    try:
        payload = response.json()
    except ValueError as error:
        raise GitLabClientError("GitLab returned invalid JSON.") from error
    if not isinstance(payload, (dict, list)):
        raise GitLabClientError("Unexpected GitLab response payload.")
    return payload


def _normalize_merge_request(payload: dict[str, Any]) -> ChangeRequestInfo:
    """Normalize a GitLab merge request payload."""
    iid = payload.get("iid")
    web_url = payload.get("web_url")
    title = payload.get("title")
    if not isinstance(iid, int) or not isinstance(web_url, str) or not isinstance(title, str):
        raise GitLabClientError("Unexpected GitLab merge request structure.")
    return ChangeRequestInfo(iid=iid, web_url=web_url, title=title)


def _encode_form_data(items: list[tuple[str, str]]) -> bytes:
    """Encode x-www-form-urlencoded request content."""
    return urlencode(items).encode("utf-8")
