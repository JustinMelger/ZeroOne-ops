"""GitLab dashboard issue client."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import httpx

from zeroone_ops.models.config import GitLabConnectionConfig
from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.providers.gitlab_client import GitLabClientError, _parse_json_response


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
            candidate = _normalize_issue(item)
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
        return _normalize_issue(payload)

    def get_issue(self, *, project_id: str, issue_iid: int) -> GitLabIssueInfo:
        """Fetch one GitLab issue."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.get(
            f"/api/v4/projects/{encoded_project_id}/issues/{issue_iid}"
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab issue payload.")
        return _normalize_issue(payload)

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
        return _normalize_issue(payload)

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
            notes.extend(_normalize_issue_note(item) for item in payload if isinstance(item, dict))
            next_page = response.headers.get("X-Next-Page")
            if not next_page:
                break
            try:
                page = int(next_page)
            except ValueError as exc:
                raise GitLabClientError("Unexpected GitLab issue note pagination.") from exc
        return notes


def _normalize_issue(payload: dict[str, Any]) -> GitLabIssueInfo:
    """Normalize one GitLab issue payload."""
    issue_id = payload.get("id")
    iid = payload.get("iid")
    web_url = payload.get("web_url")
    title = payload.get("title")
    description = payload.get("description")
    if not isinstance(issue_id, int) or not isinstance(iid, int):
        raise GitLabClientError("Unexpected GitLab issue structure.")
    if (
        not isinstance(web_url, str)
        or not isinstance(title, str)
        or not isinstance(description, str)
    ):
        raise GitLabClientError("Unexpected GitLab issue payload fields.")
    return GitLabIssueInfo(
        id=issue_id,
        iid=iid,
        web_url=web_url,
        title=title,
        description=description,
    )


def _normalize_issue_note(payload: dict[str, Any]) -> GitLabIssueNote:
    """Normalize one GitLab issue note payload."""
    note_id = payload.get("id")
    body = payload.get("body")
    created_at = payload.get("created_at")
    author = payload.get("author")
    author_username: str | None = None
    if not isinstance(note_id, int):
        raise GitLabClientError("Unexpected GitLab issue note structure.")
    if body is not None and not isinstance(body, str):
        raise GitLabClientError("Unexpected GitLab issue note body.")
    if created_at is not None and not isinstance(created_at, str):
        raise GitLabClientError("Unexpected GitLab issue note timestamp.")
    if author is not None:
        if not isinstance(author, dict):
            raise GitLabClientError("Unexpected GitLab issue note author structure.")
        raw_username = author.get("username")
        if raw_username is not None and not isinstance(raw_username, str):
            raise GitLabClientError("Unexpected GitLab issue note author username.")
        author_username = raw_username
    return GitLabIssueNote(
        id=note_id,
        body=body,
        author_username=author_username,
        created_at=created_at,
    )
