"""GitLab API client."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import httpx

from ai_sonar_bot.models.config import GitLabConnectionConfig
from ai_sonar_bot.models.gitlab import MergeRequestInfo


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
    ) -> MergeRequestInfo | None:
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
    ) -> MergeRequestInfo:
        """Create a merge request in GitLab."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.post(
            f"/api/v4/projects/{encoded_project_id}/merge_requests",
            data={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
                "labels": ",".join(labels or []),
                "remove_source_branch": "true",
            },
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab response payload.")
        return _normalize_merge_request(payload)


def _parse_json_response(response: httpx.Response) -> dict[str, Any] | list[Any]:
    """Validate and parse a GitLab JSON response."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        message = f"GitLab request failed with status {error.response.status_code}."
        raise GitLabClientError(message) from error

    try:
        payload = response.json()
    except ValueError as error:
        raise GitLabClientError("GitLab returned invalid JSON.") from error
    if not isinstance(payload, (dict, list)):
        raise GitLabClientError("Unexpected GitLab response payload.")
    return payload


def _normalize_merge_request(payload: dict[str, Any]) -> MergeRequestInfo:
    """Normalize a GitLab merge request payload."""
    iid = payload.get("iid")
    web_url = payload.get("web_url")
    title = payload.get("title")
    if not isinstance(iid, int) or not isinstance(web_url, str) or not isinstance(title, str):
        raise GitLabClientError("Unexpected GitLab merge request structure.")
    return MergeRequestInfo(iid=iid, web_url=web_url, title=title)
