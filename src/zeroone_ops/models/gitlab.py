"""GitLab models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from zeroone_ops.models.change_request import ChangeRequestInfo, ChangeRequestState

MergeRequestInfo = ChangeRequestInfo
GitLabMergeRequestState = ChangeRequestState


class MergeRequestNote(BaseModel):
    """Represent a GitLab merge request note."""

    id: int
    web_url: str | None = None
    body: str | None = None
    author_username: str | None = None
    created_at: str | None = None


class GitLabIssueInfo(BaseModel):
    """Represent a GitLab issue used by a provider-local control-plane surface."""

    id: int
    iid: int
    web_url: str
    title: str
    description: str
    labels: list[str] = []
    state: Literal["opened", "closed"] = "opened"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GitLabIssueNote(BaseModel):
    """Represent a GitLab issue note."""

    id: int
    body: str | None = None
    author_id: int | None = None
    author_username: str | None = None
    created_at: str | None = None
