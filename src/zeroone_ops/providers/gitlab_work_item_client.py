"""GitLab issue client for work-item control-plane transport."""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote_plus

import httpx

from zeroone_ops.models.config import GitLabConnectionConfig
from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.providers.gitlab_client import GitLabClientError, _parse_json_response
from zeroone_ops.providers.gitlab_issue_payload import normalize_issue, normalize_issue_note


class GitLabWorkItemClient:
    """GitLab REST client for authoritative control-plane work-item issues."""

    def __init__(
        self,
        config: GitLabConnectionConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the GitLab work-item client."""
        self.config = config
        self._http_client = http_client or httpx.Client(
            base_url=str(config.url).rstrip("/"),
            headers={"PRIVATE-TOKEN": config.token},
            timeout=30.0,
        )

    def list_open_issues(
        self,
        *,
        project_id: str,
        labels: list[str] | None = None,
    ) -> list[GitLabIssueInfo]:
        """List every open issue with the requested labels."""
        return self.list_issues(project_id=project_id, state="opened", labels=labels)

    def list_closed_issues(
        self,
        *,
        project_id: str,
        labels: list[str] | None = None,
    ) -> list[GitLabIssueInfo]:
        """List every closed issue with the requested labels."""
        return self.list_issues(project_id=project_id, state="closed", labels=labels)

    def list_issues(
        self,
        *,
        project_id: str,
        state: Literal["opened", "closed"],
        labels: list[str] | None = None,
    ) -> list[GitLabIssueInfo]:
        """List paginated project issues in one supported state."""
        encoded_project_id = quote_plus(project_id)
        page = 1
        issues: list[GitLabIssueInfo] = []
        while True:
            response = self._http_client.get(
                f"/api/v4/projects/{encoded_project_id}/issues",
                params={
                    "state": state,
                    "labels": ",".join(labels or []),
                    "page": page,
                    "per_page": 100,
                },
            )
            payload = _parse_json_response(response)
            if not isinstance(payload, list):
                raise GitLabClientError("Unexpected GitLab issue list payload.")
            issues.extend(normalize_issue(item) for item in payload if isinstance(item, dict))
            next_page = response.headers.get("X-Next-Page")
            if not next_page:
                break
            try:
                page = int(next_page)
            except ValueError as error:
                raise GitLabClientError("Unexpected GitLab issue pagination.") from error
        return issues

    def create_issue(
        self,
        *,
        project_id: str,
        title: str,
        description: str,
        labels: list[str],
    ) -> GitLabIssueInfo:
        """Create one authoritative GitLab work-item issue."""
        payload = self._issue_payload(
            self._http_client.post(
                self._issues_path(project_id),
                data={"title": title, "description": description, "labels": ",".join(labels)},
            ),
            error_message="Unexpected GitLab work-item issue payload.",
        )
        return normalize_issue(payload)

    def update_issue(
        self,
        *,
        project_id: str,
        issue_iid: int,
        title: str,
        description: str,
        labels: list[str],
    ) -> GitLabIssueInfo:
        """Update one authoritative GitLab work-item issue."""
        payload = self._issue_payload(
            self._http_client.put(
                self._issue_path(project_id, issue_iid),
                data={"title": title, "description": description, "labels": ",".join(labels)},
            ),
            error_message="Unexpected GitLab work-item issue update payload.",
        )
        return normalize_issue(payload)

    def close_issue(self, *, project_id: str, issue_iid: int) -> GitLabIssueInfo:
        """Close one authoritative GitLab work-item issue."""
        payload = self._issue_payload(
            self._http_client.put(
                self._issue_path(project_id, issue_iid),
                data={"state_event": "close"},
            ),
            error_message="Unexpected GitLab work-item issue close payload.",
        )
        return normalize_issue(payload)

    def list_issue_notes(
        self,
        *,
        project_id: str,
        issue_iid: int,
    ) -> list[GitLabIssueNote]:
        """List every note for one work-item issue across paginated responses."""
        page = 1
        notes: list[GitLabIssueNote] = []
        while True:
            response = self._http_client.get(
                f"{self._issue_path(project_id, issue_iid)}/notes",
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
            except ValueError as error:
                raise GitLabClientError("Unexpected GitLab issue note pagination.") from error
        return notes

    def get_project_member_access_level(self, *, project_id: str, user_id: int) -> int:
        """Return one user's effective project access level."""
        response = self._http_client.get(
            f"/api/v4/projects/{quote_plus(project_id)}/members/all/{user_id}"
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab project member payload.")
        access_level = payload.get("access_level")
        if isinstance(access_level, bool) or not isinstance(access_level, int):
            raise GitLabClientError("Unexpected GitLab project member access level.")
        return access_level

    def _issues_path(self, project_id: str) -> str:
        """Return the issue collection path for one GitLab project."""
        return f"/api/v4/projects/{quote_plus(project_id)}/issues"

    def _issue_path(self, project_id: str, issue_iid: int) -> str:
        """Return the issue resource path for one GitLab project issue."""
        return f"{self._issues_path(project_id)}/{issue_iid}"

    def _issue_payload(self, response: httpx.Response, *, error_message: str) -> dict[str, object]:
        """Parse one GitLab issue response with a transport-local error message."""
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError(error_message)
        return payload
