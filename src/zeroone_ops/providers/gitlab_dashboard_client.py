"""GitLab dashboard issue client."""

from __future__ import annotations

from urllib.parse import quote_plus

import httpx

from zeroone_ops.models.config import GitLabConnectionConfig
from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.providers.gitlab_client import GitLabClientError, _parse_json_response
from zeroone_ops.providers.gitlab_issue_payload import normalize_issue, normalize_issue_note


class GitLabDashboardClient:
    """GitLab REST client for dashboard issue management."""

    def __init__(
        self,
        config: GitLabConnectionConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the dashboard client."""
        self.config = config
        self._http_client = http_client or httpx.Client(
            base_url=str(config.url).rstrip("/"),
            headers={"PRIVATE-TOKEN": config.token},
            timeout=30.0,
        )

    def find_open_issue(
        self,
        *,
        project_id: str,
        title: str,
        labels: list[str] | None = None,
    ) -> GitLabIssueInfo | None:
        """Find an existing open dashboard issue by exact title."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.get(
            f"/api/v4/projects/{encoded_project_id}/issues",
            params={
                "state": "opened",
                "search": title,
                "labels": ",".join(labels or []),
            },
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, list):
            raise GitLabClientError("Unexpected GitLab issue list payload.")
        for item in payload:
            if not isinstance(item, dict):
                continue
            candidate = normalize_issue(item)
            if candidate.title == title:
                return candidate
        return None

    def create_issue(
        self,
        *,
        project_id: str,
        title: str,
        description: str,
        labels: list[str] | None = None,
    ) -> GitLabIssueInfo:
        """Create one GitLab issue."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.post(
            f"/api/v4/projects/{encoded_project_id}/issues",
            data={
                "title": title,
                "description": description,
                "labels": ",".join(labels or []),
            },
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab issue payload.")
        return normalize_issue(payload)

    def get_issue(self, *, project_id: str, issue_iid: int) -> GitLabIssueInfo:
        """Fetch one GitLab issue."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.get(
            f"/api/v4/projects/{encoded_project_id}/issues/{issue_iid}"
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab issue payload.")
        return normalize_issue(payload)

    def update_issue(
        self,
        *,
        project_id: str,
        issue_iid: int,
        description: str,
    ) -> GitLabIssueInfo:
        """Update one GitLab issue body."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.put(
            f"/api/v4/projects/{encoded_project_id}/issues/{issue_iid}",
            data={"description": description},
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab issue payload.")
        return normalize_issue(payload)

    def list_issue_notes(
        self,
        *,
        project_id: str,
        issue_iid: int,
    ) -> list[GitLabIssueNote]:
        """List every note for one GitLab issue across paginated responses."""
        encoded_project_id = quote_plus(project_id)
        page = 1
        notes: list[GitLabIssueNote] = []
        while True:
            response = self._http_client.get(
                f"/api/v4/projects/{encoded_project_id}/issues/{issue_iid}/notes",
                params={"page": page, "per_page": 100},
            )
            payload = _parse_json_response(response)
            if not isinstance(payload, list):
                raise GitLabClientError("Unexpected GitLab issue notes payload.")
            notes.extend(normalize_issue_note(item) for item in payload if isinstance(item, dict))
            next_page = response.headers.get("X-Next-Page")
            if not next_page:
                break
            try:
                page = int(next_page)
            except ValueError as exc:
                raise GitLabClientError("Unexpected GitLab issue note pagination.") from exc
        return notes

    def get_project_member_access_level(
        self,
        *,
        project_id: str,
        user_id: int,
    ) -> int:
        """Return one user's effective project access level."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.get(
            f"/api/v4/projects/{encoded_project_id}/members/all/{user_id}"
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab project member payload.")
        access_level = payload.get("access_level")
        if isinstance(access_level, bool) or not isinstance(access_level, int):
            raise GitLabClientError("Unexpected GitLab project member access level.")
        return access_level

    def create_issue_note(
        self,
        *,
        project_id: str,
        issue_iid: int,
        body: str,
    ) -> GitLabIssueNote:
        """Create one note on a GitLab issue."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.post(
            f"/api/v4/projects/{encoded_project_id}/issues/{issue_iid}/notes",
            data={"body": body},
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab issue note payload.")
        return normalize_issue_note(payload)
