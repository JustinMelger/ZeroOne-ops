"""Review workflow models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MergeRequestChangedFile(BaseModel):
    """Represent a changed file in a merge request."""

    old_path: str
    new_path: str
    diff: str | None = None
    deleted_file: bool = False
    new_file: bool = False
    renamed_file: bool = False


class MergeRequestReviewCandidate(BaseModel):
    """Represent a merge request candidate for automated review."""

    iid: int
    title: str
    description: str | None = None
    source_branch: str
    target_branch: str
    web_url: str
    head_sha: str
    draft: bool = False
    author_username: str | None = None
    changes: list[MergeRequestChangedFile] = Field(default_factory=list)
