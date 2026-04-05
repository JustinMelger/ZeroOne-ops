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


class MergeRequestNote(BaseModel):
    """Represent a published GitLab merge request note."""

    id: int
    web_url: str
