"""Shared normalization for GitLab issue and issue-note API payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.providers.gitlab_client import GitLabClientError


def normalize_issue(payload: dict[str, Any]) -> GitLabIssueInfo:
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
        labels=_normalize_issue_labels(payload),
        state=_normalize_issue_state(payload),
        created_at=_optional_issue_timestamp(payload, key="created_at"),
        updated_at=_optional_issue_timestamp(payload, key="updated_at"),
    )


def normalize_issue_note(payload: dict[str, Any]) -> GitLabIssueNote:
    """Normalize one GitLab issue note payload."""
    note_id = payload.get("id")
    body = payload.get("body")
    created_at = payload.get("created_at")
    author = payload.get("author")
    author_id: int | None = None
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
        raw_author_id = author.get("id")
        raw_username = author.get("username")
        if raw_author_id is not None and (
            isinstance(raw_author_id, bool) or not isinstance(raw_author_id, int)
        ):
            raise GitLabClientError("Unexpected GitLab issue note author ID.")
        if raw_username is not None and not isinstance(raw_username, str):
            raise GitLabClientError("Unexpected GitLab issue note author username.")
        author_id = raw_author_id
        author_username = raw_username
    return GitLabIssueNote(
        id=note_id,
        body=body,
        author_id=author_id,
        author_username=author_username,
        created_at=created_at,
    )


def _normalize_issue_labels(payload: dict[str, Any]) -> list[str]:
    """Return optional GitLab issue labels without changing legacy consumers."""
    labels = payload.get("labels", [])
    if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
        raise GitLabClientError("Unexpected GitLab issue labels.")
    return labels


def _normalize_issue_state(payload: dict[str, Any]) -> Literal["opened", "closed"]:
    """Return the supported issue state, defaulting legacy payloads to open."""
    state = payload.get("state", "opened")
    if state == "opened":
        return "opened"
    if state == "closed":
        return "closed"
    raise GitLabClientError("Unexpected GitLab issue state.")


def _optional_issue_timestamp(payload: dict[str, Any], *, key: str) -> datetime | None:
    """Return one optional timezone-aware GitLab issue timestamp."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise GitLabClientError(f"Unexpected GitLab issue {key} timestamp.")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GitLabClientError(f"Unexpected GitLab issue {key} timestamp.") from error
    if timestamp.tzinfo is None:
        raise GitLabClientError(f"Unexpected GitLab issue {key} timestamp.")
    return timestamp
