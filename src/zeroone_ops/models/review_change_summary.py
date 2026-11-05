"""Bounded descriptive review metadata, separate from finding decisions."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewChangeSummary(BaseModel):
    """Describe supplied changes without asserting approval or verified fixes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    bullets: tuple[Annotated[str, Field(strict=True, min_length=1, max_length=300)], ...] = Field(
        min_length=1, max_length=3
    )

    @field_validator("bullets", mode="before")
    @classmethod
    def normalize_whitespace(cls, value: object) -> object:
        """Normalize whole bullets without discarding entries or truncating claims."""
        if not isinstance(value, (list, tuple)):
            raise ValueError("Review change summary bullets must be an ordered array.")
        return tuple(
            " ".join(bullet.split()) if isinstance(bullet, str) else bullet for bullet in value
        )
