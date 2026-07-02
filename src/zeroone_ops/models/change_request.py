"""Provider-neutral change-request models."""

from pydantic import BaseModel


class ChangeRequestInfo(BaseModel):
    """Represent a created or reused provider-backed change request.

    Attributes:
        iid: Provider-local internal change-request identifier.
        web_url: Browser URL for the change request.
        title: Change-request title.
    """

    iid: int
    web_url: str
    title: str
