"""Bounded commit labels for review presentation, never review authority."""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewedCommitMetadata(BaseModel):
    """Identify the exact commit supplying an optional presentation label."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    head_sha: str = Field(min_length=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    web_url: str | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, title: str | None) -> str | None:
        """Require stored labels to be trimmed single lines, not full messages."""
        if title is not None and (title != title.strip() or len(title.splitlines()) != 1):
            raise ValueError("Reviewed commit title must be a trimmed single line.")
        return title
