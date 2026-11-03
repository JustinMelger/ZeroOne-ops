"""Versioned provider-backed review history, independent of transport identity."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from zeroone_ops.models.review import (
    ChangeRequestDiffRefs,
    PublishableReviewArtifact,
    ReviewClassification,
    ReviewInlineCommentDecision,
)
from zeroone_ops.models.reviewed_commit import ReviewedCommitMetadata


class ReviewOverviewSummary(BaseModel):
    """Identify a completed pass without claiming to retain its artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pass_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    completed_at: datetime
    classification: ReviewClassification
    findings_count: int = Field(ge=0)
    workflow_url: str | None = None
    reviewed_commit: ReviewedCommitMetadata | None = None

    @model_validator(mode="after")
    def validate_commit_metadata(self) -> ReviewOverviewSummary:
        """Keep optional labels correlated with their exact history head."""
        if self.reviewed_commit is not None and self.reviewed_commit.head_sha != self.head_sha:
            raise ValueError("Reviewed commit metadata must match its history head.")
        return self


class ReviewOverviewPass(BaseModel):
    """Retain complete finalized meaning and recoverable publication side effects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pass_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    head_sha: str = Field(min_length=1)
    sequence: int = Field(gt=0)
    completed_at: datetime
    diff_refs: ChangeRequestDiffRefs | None = None
    artifact: PublishableReviewArtifact
    inline_decisions: list[ReviewInlineCommentDecision] = Field(default_factory=list)
    projection_pending: bool = True
    projection_warning: str | None = None
    projection_reference: str | None = None
    workflow_url: str | None = None
    verified_work_item_url: str | None = None
    reviewed_commit: ReviewedCommitMetadata | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> ReviewOverviewPass:
        """Reject contradictory commit provenance or naive completion times."""
        if self.completed_at.utcoffset() is None:
            raise ValueError("Review completion time must be timezone aware.")
        if self.diff_refs is not None and self.diff_refs.head_sha != self.head_sha:
            raise ValueError("Review diff head must match its completed pass.")
        if self.reviewed_commit is not None and self.reviewed_commit.head_sha != self.head_sha:
            raise ValueError("Reviewed commit metadata must match its completed pass.")
        return self

    def summary(self) -> ReviewOverviewSummary:
        """Project only factual history fields, without manufacturing evidence."""
        return ReviewOverviewSummary(
            pass_id=self.pass_id,
            run_id=self.run_id,
            head_sha=self.head_sha,
            sequence=self.sequence,
            completed_at=self.completed_at,
            classification=self.artifact.classification,
            findings_count=len(self.artifact.findings),
            workflow_url=self.workflow_url,
            reviewed_commit=self.reviewed_commit,
        )


class ReviewOverviewEnvelope(BaseModel):
    """Store two complete passes and five summaries in exact-request scope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["zeroone/review-overview/v1"] = "zeroone/review-overview/v1"
    platform: Literal["github", "gitlab"]
    repository_id: str = Field(min_length=1)
    change_request_number: int = Field(gt=0)
    complete_passes: list[ReviewOverviewPass] = Field(min_length=1, max_length=2)
    history: list[ReviewOverviewSummary] = Field(min_length=1, max_length=5)
    execution_notice: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_history(self) -> ReviewOverviewEnvelope:
        """Require ordered, unique history consistent with every complete snapshot."""
        for records in (self.complete_passes, self.history):
            sequences = [record.sequence for record in records]
            identities = [record.pass_id for record in records]
            if sequences != sorted(set(sequences), reverse=True):
                raise ValueError("Overview history must have unique descending sequences.")
            if len(identities) != len(set(identities)):
                raise ValueError("Overview pass identities must be unique.")
        summaries = {record.pass_id: record for record in self.history}
        for snapshot in self.complete_passes:
            if summaries.get(snapshot.pass_id) != snapshot.summary():
                raise ValueError("Complete review snapshots must match their history summaries.")
        if self.complete_passes[0].pass_id != self.history[0].pass_id:
            raise ValueError("Current review must be the latest logical pass.")
        return self
