"""Review workflow models."""

from __future__ import annotations

from typing import Literal

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


class ReviewFileContext(BaseModel):
    """Represent one changed file plus bounded local source context."""

    file_path: str
    diff: str | None = None
    start_line: int
    end_line: int
    content: str
    full_file_included: bool
    truncated: bool
    new_file: bool = False
    deleted_file: bool = False
    renamed_file: bool = False


class MergeRequestReviewContext(BaseModel):
    """Represent deterministic review context for one merge request."""

    mr_iid: int
    title: str
    description: str | None = None
    source_branch: str
    target_branch: str
    web_url: str
    head_sha: str
    draft: bool = False
    author_username: str | None = None
    changed_files: list[ReviewFileContext] = Field(default_factory=list)


class ReviewFinding(BaseModel):
    """Represent one structured review finding."""

    severity: Literal["high", "medium", "low"]
    file_path: str
    title: str
    explanation: str
    suggested_follow_up: str


class ReviewResult(BaseModel):
    """Represent the structured result of one review pass."""

    classification: Literal["no_findings", "findings_present", "manual_review_only"]
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)
