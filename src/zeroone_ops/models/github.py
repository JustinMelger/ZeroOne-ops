"""GitHub provider-local models."""

from datetime import datetime

from pydantic import BaseModel


class GitHubIssueInfo(BaseModel):
    """Represent a GitHub issue used by provider-local control-plane transport."""

    id: int
    number: int
    web_url: str
    title: str
    body: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GitHubIssueComment(BaseModel):
    """Represent a GitHub issue comment."""

    id: int
    web_url: str | None = None
    body: str | None = None
    author_username: str | None = None
    created_at: str | None = None
