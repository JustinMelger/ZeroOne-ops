"""Provider-neutral work-item models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from zeroone_ops.models.analysis import RemediationIntent, SemanticSafetyAssessment
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
    "policy_deferred",
    "capacity_deferred",
    "review_feedback_required",
    "review_revision_queued",
]
RecoveryAction = Literal["dismiss", "requeue"]
RecoveryPlan = Literal["retry_publication", "start_fresh"]
WorkItemResolution = Literal["merged", "no_change_required", "no_longer_detected"]

ACTIVE_REMEDIATION_STATUSES = frozenset(
    {"approved", "in_progress", "review_feedback_required", "review_revision_queued"}
)
PROTECTED_REMEDIATION_STATUSES = frozenset(
    {
        "blocked",
        "dismissed",
        "in_progress",
        "review_feedback_required",
        "review_revision_queued",
    }
)


def is_active_remediation_status(status: WorkItemStatus) -> bool:
    """Return whether a work-item status consumes active remediation capacity."""
    return status in ACTIVE_REMEDIATION_STATUSES


def is_protected_remediation_status(status: WorkItemStatus) -> bool:
    """Return whether finding sync must retain an execution-owned work item."""
    return status in PROTECTED_REMEDIATION_STATUSES


def is_review_feedback_status(status: WorkItemStatus) -> bool:
    """Return whether one open work item is owned by remediation review feedback."""
    return status in {"review_feedback_required", "review_revision_queued"}


def work_item_resolution_display_name(resolution: WorkItemResolution) -> str:
    """Return the operator-facing label for one terminal work-item resolution."""
    return {
        "merged": "Merged",
        "no_change_required": "No change required",
        "no_longer_detected": "No longer detected",
    }[resolution]


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
    review_note_url: str | None = None
    review_note_reference: str | None = None
    follow_up_required: bool
    feedback: ProjectedReviewFeedback | None = None


class ProjectedReviewFinding(BaseModel):
    """Persist one bounded actionable review finding for a remediation revision."""

    title: str = Field(min_length=1, max_length=300)
    file_path: str = Field(min_length=1, max_length=500)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    evidence: str = Field(min_length=1, max_length=1_000)
    explanation: str = Field(min_length=1, max_length=1_000)
    suggested_follow_up: str = Field(min_length=1, max_length=1_000)


class ProjectedReviewFeedback(BaseModel):
    """Persist the compact review evidence eligible for a bounded revision."""

    summary: str = Field(min_length=1, max_length=1_000)
    finding_count: int = Field(ge=1, le=20)
    findings: list[ProjectedReviewFinding] = Field(min_length=1, max_length=20)


class ReviewRevisionRequest(BaseModel):
    """Record one authorized request to revise the linked change request."""

    actor: str = Field(min_length=1, max_length=200)
    request_reference: str = Field(min_length=1, max_length=300)
    occurred_at: datetime
    reviewed_sha: str = Field(min_length=1, max_length=200)


class WorkItemClaim(BaseModel):
    """Represent durable ownership while a remediation work item is executing."""

    claimed_at: datetime
    run_id: str | None = None


class PublicationRetryState(BaseModel):
    """Record the only remote branch state that may be explicitly retried later."""

    branch_name: str
    commit_sha: str
    reason: Literal["change_request_publish_failed"]
    remediation_intent: RemediationIntent = "chore"
    semantic_safety: SemanticSafetyAssessment | None = None


class WorkItemExecutionFailure(BaseModel):
    """Record concise, operator-facing context for a blocked execution."""

    stage: str
    summary: str
    retry_count: int
    run_id: str
    occurred_at: datetime
    failed_command: str | None = None
    exit_code: int | None = None
    execution_url: str | None = None
    validation_outcome: str | None = None
    status: Literal["blocked", "dismissed"] = "blocked"


class WorkItemSemanticSafety(BaseModel):
    """Persist compact untrusted semantic-safety evidence for an execution attempt."""

    assessment: SemanticSafetyAssessment | None = None
    rejection_reason: str | None = None


class WorkItemPolicyDeferral(BaseModel):
    """Record why a work item was reversibly deferred by policy."""

    reason: str
    run_id: str
    occurred_at: datetime


class WorkItemCapacityDeferral(BaseModel):
    """Record why a work item is waiting outside active remediation capacity."""

    reason: Literal["promotion_capacity_exhausted"]
    run_id: str
    occurred_at: datetime


class RecoveryEvent(BaseModel):
    """Record one accepted operator recovery decision for a work item."""

    action: RecoveryAction
    actor: str
    request_reference: str
    occurred_at: datetime
    previous_status: str
    resulting_status: str
    previous_attempt_number: int = Field(ge=1)
    resulting_attempt_number: int = Field(ge=1)
    plan: RecoveryPlan | None = None
    reason: str | None = None
    prior_change_request: ChangeRequestRef | None = None
    prior_publication_retry: PublicationRetryState | None = None
    prior_execution_failure: WorkItemExecutionFailure | None = None


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
    review_revision_request: ReviewRevisionRequest | None = None
    last_revision_command: ReviewRevisionRequest | None = None
    review_action_required_at: datetime | None = None
    claim: WorkItemClaim | None = None
    publication_retry: PublicationRetryState | None = None
    execution_failure: WorkItemExecutionFailure | None = None
    semantic_safety: WorkItemSemanticSafety | None = None
    policy_deferral: WorkItemPolicyDeferral | None = None
    capacity_deferral: WorkItemCapacityDeferral | None = None
    attempt_number: int = Field(default=1, ge=1)
    recovery_events: list[RecoveryEvent] = Field(default_factory=list)
    resolution: WorkItemResolution | None = None
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
