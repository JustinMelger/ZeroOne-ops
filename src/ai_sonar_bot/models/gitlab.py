"""GitLab models."""

from pydantic import BaseModel


class MergeRequestInfo(BaseModel):
    """Represent a created GitLab merge request.

    Attributes:
        iid: GitLab merge request internal ID.
        web_url: Browser URL for the merge request.
        title: Merge request title.
    """

    iid: int
    web_url: str
    title: str


class GitLabMergeRequestState(BaseModel):
    """Represent the reconciliation-relevant state of one GitLab merge request."""

    iid: int
    web_url: str
    source_branch: str
    head_sha: str
    state: str


class MergeRequestNote(BaseModel):
    """Represent a GitLab merge request note."""

    id: int
    web_url: str | None = None
    body: str | None = None
    author_username: str | None = None
    created_at: str | None = None


class GitLabIssueInfo(BaseModel):
    """Represent a GitLab issue used by the dashboard."""

    id: int
    iid: int
    web_url: str
    title: str
    description: str
