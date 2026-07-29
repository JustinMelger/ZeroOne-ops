"""Provider-neutral work-item models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from zeroone_ops.models.finding import RemediationContext
from zeroone_ops.models.review import ReviewClassification

WorkItemKind = Literal["remediation"]
WorkItemStatus = Literal[
    "candidate",
    "approved",
    "in_progress",
    "blocked",
    "completed",
    "dismissed",
]


class ChangeRequestRef(BaseModel):
    """Represent one linked provider-backed change request."""

    number: int
    web_url: str


class WorkItemSourceRef(BaseModel):
    """Represent the stable source identity for one work item."""

    source: str
    source_item_key: str
    repository_scope: str | None = None


class ProjectedReviewState(BaseModel):
    """Represent bounded review status and traceability for one work item."""

    classification: ReviewClassification
    reviewed_sha: str
    review_note_url: str
    follow_up_required: bool


class WorkItemClaim(BaseModel):
    """Represent durable ownership while a remediation work item is executing."""

    claimed_at: datetime
    run_id: str | None = None


class PublicationRetryState(BaseModel):
    """Record the only remote branch state that may be explicitly retried later."""

    branch_name: str
    commit_sha: str
    reason: Literal["change_request_publish_failed"]


class WorkItemState(BaseModel):
    """Represent one canonical provider-neutral work item."""

    work_item_id: str
    kind: WorkItemKind
    status: WorkItemStatus
    source: WorkItemSourceRef
    summary: str
    detail: str | None = None
    severity: str | None = None
    file_path: str | None = None
    line: int | None = None
    remediation_context: RemediationContext = Field(default_factory=RemediationContext)
    linked_change_request: ChangeRequestRef | None = None
    projected_review: ProjectedReviewState | None = None
    claim: WorkItemClaim | None = None
    publication_retry: PublicationRetryState | None = None
    created_by_system: Literal["zeroone_ops"] = "zeroone_ops"

    @property
    def identity_key(self) -> tuple[str, str, str | None, WorkItemKind]:
        """Return the stable identity key for open-item reuse."""
        return (
            self.source.source,
            self.source.source_item_key,
            self.source.repository_scope,
            self.kind,
        )
