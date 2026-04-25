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
    helper_context: list[ReviewHelperContext] = Field(default_factory=list)


class ReviewHelperContext(BaseModel):
    """Represent one bounded supplemental helper snippet for review."""

    file_path: str
    symbol: str
    start_line: int
    end_line: int
    content: str


class RemediationReviewContext(BaseModel):
    """Represent remediation-authored MR metadata when present."""

    summary: str | None = None
    source: str | None = None
    item_reference_label: str | None = None
    item_reference: str | None = None
    rule_id: str | None = None
    severity: str | None = None
    remediation_type: str | None = None
    file_path: str | None = None
    line: int | None = None
    message: str | None = None
    validation_summary: str | None = None
    notes: str | None = None


class RepositoryGuidanceContext(BaseModel):
    """Represent one bounded repository guidance excerpt for review."""

    file_path: str
    summary: str


class PriorReviewFinding(BaseModel):
    """Represent one bounded prior-review finding summary."""

    identity: str | None = None
    legacy_identity: str | None = None
    summary: str
    severity: str | None = None
    symbol: str | None = None
    issue_kind: str | None = None
    region_hint: str | None = None


class PriorReviewPass(BaseModel):
    """Represent one bounded prior review pass on the same merge request."""

    reviewed_head_sha: str
    classification: Literal["no_findings", "findings_present", "manual_review_only"]
    findings_count: int
    summary: str | None = None
    note_url: str | None = None
    findings: list[PriorReviewFinding] = Field(default_factory=list)


class PriorReviewContext(BaseModel):
    """Represent bounded prior review history for the same merge request."""

    merge_request_iid: int
    passes: list[PriorReviewPass] = Field(default_factory=list)


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
    remediation_context: RemediationReviewContext | None = None
    prior_review_context: PriorReviewContext | None = None
    repository_guidance: list[RepositoryGuidanceContext] = Field(default_factory=list)
    changed_files: list[ReviewFileContext] = Field(default_factory=list)


class ReviewFinding(BaseModel):
    """Represent one structured review finding."""

    severity: Literal["high", "medium", "low"]
    file_path: str
    symbol: str | None = None
    issue_kind: str | None = None
    region_hint: str | None = None
    title: str
    evidence: str
    explanation: str
    suggested_follow_up: str


class ReviewResult(BaseModel):
    """Represent the structured result of one review pass."""

    classification: Literal["no_findings", "findings_present", "manual_review_only"]
    summary: str
    review_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    review_confidence_reason: str | None = None
    findings: list[ReviewFinding] = Field(default_factory=list)


class OverlapCandidate(BaseModel):
    """Represent one app-owned overlap candidate pair for reconciliation."""

    current_finding_index: int
    prior_finding_index: int
    reasons: list[str] = Field(default_factory=list)


class OverlapPacket(BaseModel):
    """Represent one bounded overlap packet for a single MR review run."""

    merge_request_iid: int
    current_head_sha: str
    prior_head_sha: str
    current_findings: list[ReviewFinding] = Field(default_factory=list)
    prior_findings: list[PriorReviewFinding] = Field(default_factory=list)
    candidates: list[OverlapCandidate] = Field(default_factory=list)


class OverlapResolution(BaseModel):
    """Represent one normalized overlap outcome."""

    outcome: Literal[
        "still_unresolved",
        "new_in_this_pass",
        "no_longer_present",
        "overlap_ambiguous",
    ]
    current_finding_index: int | None = None
    prior_finding_index: int | None = None
    related_prior_finding_indices: list[int] = Field(default_factory=list)


class OverlapReconciliationResult(BaseModel):
    """Represent normalized overlap outcomes for one prior-current pass pair."""

    prior_reviewed_head_sha: str
    resolutions: list[OverlapResolution] = Field(default_factory=list)
