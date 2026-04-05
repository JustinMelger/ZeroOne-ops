"""GitLab review API client."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import httpx

from ai_sonar_bot.models.config import GitLabConnectionConfig
from ai_sonar_bot.models.gitlab import MergeRequestNote
from ai_sonar_bot.models.review import MergeRequestChangedFile, MergeRequestReviewCandidate
from ai_sonar_bot.providers.gitlab_client import GitLabClientError, _parse_json_response


class GitLabReviewClient:
    """GitLab REST client for merge request review intake."""

    def __init__(
        self,
        config: GitLabConnectionConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the GitLab review client."""
        self.config = config
        self._http_client = http_client or httpx.Client(
            base_url=str(config.url).rstrip("/"),
            headers={"PRIVATE-TOKEN": config.token},
            timeout=30.0,
        )

    def list_open_merge_requests(self, *, project_id: str) -> list[MergeRequestReviewCandidate]:
        """List open merge requests for review."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.get(
            f"/api/v4/projects/{encoded_project_id}/merge_requests",
            params={"state": "opened", "order_by": "updated_at", "sort": "asc"},
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, list):
            raise GitLabClientError("Unexpected GitLab merge request list payload.")
        return [_normalize_review_candidate(item) for item in payload if isinstance(item, dict)]

    def get_merge_request(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> MergeRequestReviewCandidate:
        """Fetch one merge request with change metadata."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.get(
            f"/api/v4/projects/{encoded_project_id}/merge_requests/{merge_request_iid}/changes"
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab merge request detail payload.")
        return _normalize_review_candidate(payload)

    def create_merge_request_note(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        body: str,
    ) -> MergeRequestNote:
        """Publish one merge request note."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.post(
            f"/api/v4/projects/{encoded_project_id}/merge_requests/{merge_request_iid}/notes",
            data={"body": body},
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab merge request note payload.")
        return _normalize_merge_request_note(payload)


def _normalize_review_candidate(payload: dict[str, Any]) -> MergeRequestReviewCandidate:
    """Normalize a GitLab merge request payload for review."""
    iid = payload.get("iid")
    title = payload.get("title")
    source_branch = payload.get("source_branch")
    target_branch = payload.get("target_branch")
    web_url = payload.get("web_url")
    head_sha = payload.get("sha")
    draft = payload.get("draft", False)
    description = payload.get("description")
    author_payload = payload.get("author")
    changes_payload = payload.get("changes", [])

    if not isinstance(iid, int) or not isinstance(title, str):
        raise GitLabClientError("Unexpected GitLab merge request structure.")
    if not isinstance(source_branch, str) or not isinstance(target_branch, str):
        raise GitLabClientError("Unexpected GitLab merge request branch structure.")
    if not isinstance(web_url, str) or not isinstance(head_sha, str):
        raise GitLabClientError("Unexpected GitLab merge request link structure.")
    if description is not None and not isinstance(description, str):
        raise GitLabClientError("Unexpected GitLab merge request description.")
    if not isinstance(draft, bool):
        raise GitLabClientError("Unexpected GitLab merge request draft flag.")

    author_username: str | None = None
    if author_payload is not None:
        if not isinstance(author_payload, dict):
            raise GitLabClientError("Unexpected GitLab merge request author structure.")
        username = author_payload.get("username")
        if username is not None and not isinstance(username, str):
            raise GitLabClientError("Unexpected GitLab merge request author username.")
        author_username = username

    if not isinstance(changes_payload, list):
        raise GitLabClientError("Unexpected GitLab merge request changes structure.")

    return MergeRequestReviewCandidate(
        iid=iid,
        title=title,
        description=description,
        source_branch=source_branch,
        target_branch=target_branch,
        web_url=web_url,
        head_sha=head_sha,
        draft=draft,
        author_username=author_username,
        changes=[
            _normalize_changed_file(change)
            for change in changes_payload
            if isinstance(change, dict)
        ],
    )


def _normalize_changed_file(payload: dict[str, Any]) -> MergeRequestChangedFile:
    """Normalize one changed-file entry."""
    old_path = payload.get("old_path")
    new_path = payload.get("new_path")
    diff = payload.get("diff")
    deleted_file = payload.get("deleted_file", False)
    new_file = payload.get("new_file", False)
    renamed_file = payload.get("renamed_file", False)

    if not isinstance(old_path, str) or not isinstance(new_path, str):
        raise GitLabClientError("Unexpected GitLab changed file structure.")
    if diff is not None and not isinstance(diff, str):
        raise GitLabClientError("Unexpected GitLab changed file diff.")
    if not all(isinstance(value, bool) for value in (deleted_file, new_file, renamed_file)):
        raise GitLabClientError("Unexpected GitLab changed file flags.")

    return MergeRequestChangedFile(
        old_path=old_path,
        new_path=new_path,
        diff=diff,
        deleted_file=deleted_file,
        new_file=new_file,
        renamed_file=renamed_file,
    )


def _normalize_merge_request_note(payload: dict[str, Any]) -> MergeRequestNote:
    """Normalize a GitLab merge request note payload."""
    note_id = payload.get("id")
    web_url = payload.get("web_url")
    if not isinstance(note_id, int) or not isinstance(web_url, str):
        raise GitLabClientError("Unexpected GitLab merge request note structure.")
    return MergeRequestNote(id=note_id, web_url=web_url)
