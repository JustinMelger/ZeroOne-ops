"""GitLab review API client."""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import quote_plus

import httpx

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.config import GitLabConnectionConfig
from zeroone_ops.models.gitlab import GitLabMergeRequestState, MergeRequestNote
from zeroone_ops.models.review import (
    ChangeRequestChangedFile,
    ChangeRequestDiffRefs,
    ChangeRequestReviewCandidate,
    ReviewComment,
)
from zeroone_ops.providers.gitlab_client import GitLabClientError, _parse_json_response
from zeroone_ops.providers.review.platform import ReviewPlatformClientError


class GitLabReviewClientProtocol(Protocol):
    """Structural interface for review-oriented GitLab access."""

    def list_open_merge_requests(self, *, project_id: str) -> list[ChangeRequestReviewCandidate]:
        """List open merge requests for review."""

    def get_merge_request(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> ChangeRequestReviewCandidate:
        """Fetch one merge request with change metadata."""

    def get_change_request_state(
        self,
        *,
        project_id: str,
        change_request_number: int,
    ) -> ChangeRequestState:
        """Fetch one change-request state for reconciliation."""

    def get_merge_request_state(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> GitLabMergeRequestState:
        """Fetch one merge request state for reconciliation."""

    def create_merge_request_note(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        body: str,
    ) -> MergeRequestNote:
        """Publish one merge request note."""

    def update_merge_request_note(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        note_id: int,
        body: str,
    ) -> MergeRequestNote:
        """Update one merge request note."""

    def create_merge_request_inline_comment(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        body: str,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        old_path: str,
        new_path: str,
        new_line: int,
    ) -> MergeRequestNote:
        """Publish one merge-request inline comment discussion."""

    def list_merge_request_notes(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> list[MergeRequestNote]:
        """List every note for one merge request."""

    def get_current_user_username(self) -> str:
        """Return the username associated with the active API token."""


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

    def list_open_merge_requests(self, *, project_id: str) -> list[ChangeRequestReviewCandidate]:
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
    ) -> ChangeRequestReviewCandidate:
        """Fetch one merge request with change metadata."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.get(
            f"/api/v4/projects/{encoded_project_id}/merge_requests/{merge_request_iid}/changes"
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab merge request detail payload.")
        return _normalize_review_candidate(payload)

    def get_change_request_state(
        self,
        *,
        project_id: str,
        change_request_number: int,
    ) -> ChangeRequestState:
        """Fetch one change request state using provider-neutral naming."""
        return self.get_merge_request_state(
            project_id=project_id,
            merge_request_iid=change_request_number,
        )

    def get_merge_request_state(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> GitLabMergeRequestState:
        """Fetch one merge request state for reconciliation."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.get(
            f"/api/v4/projects/{encoded_project_id}/merge_requests/{merge_request_iid}"
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab merge request state payload.")
        return _normalize_merge_request_state(payload)

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

    def update_merge_request_note(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        note_id: int,
        body: str,
    ) -> MergeRequestNote:
        """Update one merge request note."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.put(
            f"/api/v4/projects/{encoded_project_id}/merge_requests/{merge_request_iid}/notes/{note_id}",
            data={"body": body},
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab merge request note update payload.")
        return _normalize_merge_request_note(payload)

    def create_merge_request_inline_comment(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        body: str,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        old_path: str,
        new_path: str,
        new_line: int,
    ) -> MergeRequestNote:
        """Publish one inline merge-request discussion note."""
        encoded_project_id = quote_plus(project_id)
        response = self._http_client.post(
            f"/api/v4/projects/{encoded_project_id}/merge_requests/{merge_request_iid}/discussions",
            data={
                "body": body,
                "position[position_type]": "text",
                "position[base_sha]": base_sha,
                "position[start_sha]": start_sha,
                "position[head_sha]": head_sha,
                "position[old_path]": old_path,
                "position[new_path]": new_path,
                "position[new_line]": str(new_line),
            },
        )
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab merge request discussion payload.")
        notes = payload.get("notes")
        if not isinstance(notes, list) or not notes or not isinstance(notes[0], dict):
            raise GitLabClientError("Unexpected GitLab merge request discussion notes payload.")
        return _normalize_merge_request_note(notes[0])

    def list_merge_request_notes(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> list[MergeRequestNote]:
        """List every note for one merge request across paginated GitLab responses."""
        encoded_project_id = quote_plus(project_id)
        page = 1
        notes: list[MergeRequestNote] = []
        while True:
            response = self._http_client.get(
                f"/api/v4/projects/{encoded_project_id}/merge_requests/{merge_request_iid}/notes",
                params={"page": page, "per_page": 100},
            )
            payload = _parse_json_response(response)
            if not isinstance(payload, list):
                raise GitLabClientError("Unexpected GitLab merge request notes payload.")
            notes.extend(
                _normalize_merge_request_note(item) for item in payload if isinstance(item, dict)
            )
            next_page = response.headers.get("X-Next-Page")
            if not next_page:
                break
            try:
                page = int(next_page)
            except ValueError as exc:
                raise GitLabClientError("Unexpected GitLab merge request note pagination.") from exc
        return notes

    def get_current_user_username(self) -> str:
        """Return the GitLab username associated with the active API token."""
        response = self._http_client.get("/api/v4/user")
        payload = _parse_json_response(response)
        if not isinstance(payload, dict):
            raise GitLabClientError("Unexpected GitLab current user payload.")
        username = payload.get("username")
        if not isinstance(username, str):
            raise GitLabClientError("Unexpected GitLab current user username.")
        return username

    def allows_machine_safe_comment_fallback(self) -> bool:
        """Keep GitLab continuity conservative when author lookup fails."""
        return False

    def get_change_request(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> ChangeRequestReviewCandidate:
        """Fetch one pull request with change metadata using provider-neutral naming."""
        try:
            return self.get_merge_request(
                project_id=repository_id,
                merge_request_iid=change_request_number,
            )
        except GitLabClientError as error:
            raise ReviewPlatformClientError(str(error)) from error

    def list_change_request_comments(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> list[ReviewComment]:
        """List provider-backed review notes/comments using neutral naming."""
        try:
            return [
                _to_pull_request_review_note(note)
                for note in self.list_merge_request_notes(
                    project_id=repository_id,
                    merge_request_iid=change_request_number,
                )
            ]
        except GitLabClientError as error:
            raise ReviewPlatformClientError(str(error)) from error

    def create_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
    ) -> ReviewComment:
        """Publish one authoritative pull-request review note/comment."""
        try:
            return _to_pull_request_review_note(
                self.create_merge_request_note(
                    project_id=repository_id,
                    merge_request_iid=change_request_number,
                    body=body,
                )
            )
        except GitLabClientError as error:
            raise ReviewPlatformClientError(str(error)) from error

    def update_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        note_id: int,
        body: str,
    ) -> ReviewComment:
        """Update one authoritative pull-request review note/comment."""
        try:
            return _to_pull_request_review_note(
                self.update_merge_request_note(
                    project_id=repository_id,
                    merge_request_iid=change_request_number,
                    note_id=note_id,
                    body=body,
                )
            )
        except GitLabClientError as error:
            raise ReviewPlatformClientError(str(error)) from error

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
        """Publish one inline pull-request review comment."""
        try:
            return _to_pull_request_review_note(
                self.create_merge_request_inline_comment(
                    project_id=repository_id,
                    merge_request_iid=change_request_number,
                    body=body,
                    base_sha=base_sha,
                    start_sha=start_sha,
                    head_sha=head_sha,
                    old_path=old_path,
                    new_path=new_path,
                    new_line=new_line,
                )
            )
        except GitLabClientError as error:
            raise ReviewPlatformClientError(str(error)) from error


def _normalize_review_candidate(payload: dict[str, Any]) -> ChangeRequestReviewCandidate:
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
    diff_refs_payload = payload.get("diff_refs")

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
    diff_refs = _normalize_diff_refs(diff_refs_payload)

    return ChangeRequestReviewCandidate(
        change_request_number=iid,
        title=title,
        description=description,
        source_branch=source_branch,
        target_branch=target_branch,
        web_url=web_url,
        head_sha=head_sha,
        draft=draft,
        author_username=author_username,
        diff_refs=diff_refs,
        changes=[
            _normalize_changed_file(change)
            for change in changes_payload
            if isinstance(change, dict)
        ],
    )


def _normalize_changed_file(payload: dict[str, Any]) -> ChangeRequestChangedFile:
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

    return ChangeRequestChangedFile(
        old_path=old_path,
        new_path=new_path,
        diff=diff,
        deleted_file=deleted_file,
        new_file=new_file,
        renamed_file=renamed_file,
    )


def _normalize_diff_refs(payload: object) -> ChangeRequestDiffRefs | None:
    """Normalize optional GitLab diff refs for inline comment positioning."""
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise GitLabClientError("Unexpected GitLab merge request diff refs structure.")
    base_sha = payload.get("base_sha")
    start_sha = payload.get("start_sha")
    head_sha = payload.get("head_sha")
    if not all(isinstance(value, str) for value in (base_sha, start_sha, head_sha)):
        raise GitLabClientError("Unexpected GitLab merge request diff refs payload.")
    return ChangeRequestDiffRefs(
        base_sha=str(base_sha),
        start_sha=str(start_sha),
        head_sha=str(head_sha),
    )


def _normalize_merge_request_note(payload: dict[str, Any]) -> MergeRequestNote:
    """Normalize a GitLab merge request note payload."""
    note_id = payload.get("id")
    web_url = payload.get("web_url")
    body = payload.get("body")
    created_at = payload.get("created_at")
    author_payload = payload.get("author")
    if not isinstance(note_id, int):
        raise GitLabClientError("Unexpected GitLab merge request note structure.")
    if web_url is not None and not isinstance(web_url, str):
        raise GitLabClientError("Unexpected GitLab merge request note structure.")
    if body is not None and not isinstance(body, str):
        raise GitLabClientError("Unexpected GitLab merge request note body.")
    if created_at is not None and not isinstance(created_at, str):
        raise GitLabClientError("Unexpected GitLab merge request note timestamp.")

    author_username: str | None = None
    if author_payload is not None:
        if not isinstance(author_payload, dict):
            raise GitLabClientError("Unexpected GitLab merge request note author structure.")
        username = author_payload.get("username")
        if username is not None and not isinstance(username, str):
            raise GitLabClientError("Unexpected GitLab merge request note author username.")
        author_username = username

    return MergeRequestNote(
        id=note_id,
        web_url=web_url,
        body=body,
        author_username=author_username,
        created_at=created_at,
    )


def _to_pull_request_review_note(note: MergeRequestNote) -> ReviewComment:
    """Adapt a GitLab merge request note into the neutral review-note shape."""
    return ReviewComment(
        id=note.id,
        web_url=note.web_url,
        body=note.body,
        author_username=note.author_username,
        created_at=note.created_at,
    )


def _normalize_merge_request_state(payload: dict[str, Any]) -> GitLabMergeRequestState:
    """Normalize a GitLab merge request payload for reconciliation."""
    iid = payload.get("iid")
    web_url = payload.get("web_url")
    source_branch = payload.get("source_branch")
    head_sha = payload.get("sha")
    state = payload.get("state")
    if not isinstance(iid, int):
        raise GitLabClientError("Unexpected GitLab merge request state structure.")
    if not isinstance(web_url, str) or not isinstance(source_branch, str):
        raise GitLabClientError("Unexpected GitLab merge request state structure.")
    if not isinstance(head_sha, str) or not isinstance(state, str):
        raise GitLabClientError("Unexpected GitLab merge request state structure.")
    return GitLabMergeRequestState(
        iid=iid,
        web_url=web_url,
        source_branch=source_branch,
        head_sha=head_sha,
        state=state,
    )
