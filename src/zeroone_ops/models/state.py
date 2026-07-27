"""State models.

This module defines the JSON-backed application state used to track runs and
issue lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field


def utc_now() -> datetime:
    """Return the current UTC time.

    Returns:
        Current timezone-aware UTC datetime.
    """
    return datetime.now(UTC)


class RunStatus(StrEnum):
    """Enumerate terminal and transitional run states."""

    STARTED = "started"
    NO_ISSUE = "no_issue"
    SELECTED = "selected"
    ANALYZING = "analyzing"
    FIX_GENERATED = "fix_generated"
    VALIDATION_FAILED = "validation_failed"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    MR_CREATED = "mr_created"
    CHANGE_REQUEST_CREATED = "change_request_created"
    REVIEWED = "reviewed"
    SYNCED = "synced"
    RECONCILED = "reconciled"
    MANUAL = "manual"
    FAILED = "failed"


class FailureStage(StrEnum):
    """Enumerate execution stages that can fail."""

    ISSUE_INTAKE = "issue_intake"
    DASHBOARD_UPDATE = "dashboard_update"
    ANALYSIS = "analysis"
    PATCH_APPLY = "patch_apply"
    VALIDATION = "validation"
    APPROVAL = "approval"
    BRANCH_PREPARATION = "branch_preparation"
    COMMIT = "commit"
    PUBLISH = "publish"
    REVIEW_INTAKE = "review_intake"
    REVIEW_CONTEXT = "review_context"
    REVIEW_ANALYSIS = "review_analysis"
    REVIEW_PUBLISH = "review_publish"
    RECONCILIATION = "reconciliation"


class FailureDetails(BaseModel):
    """Capture structured diagnostics for a failed run stage.

    Attributes:
        stage: Execution stage that failed.
        message: Short human-readable failure summary.
        retry_count: Number of retries consumed before the failure.
        validation_summary: Validation summary when the failure happened during checks.
        failed_command: Validation command that failed, if known.
        exit_code: Exit code for the failed command, if known.
        stdout_excerpt: Truncated command stdout for debugging.
        stderr_excerpt: Truncated command stderr for debugging.
    """

    stage: FailureStage
    message: str
    retry_count: int = 0
    validation_summary: str | None = None
    failed_command: str | None = None
    exit_code: int | None = None
    stdout_excerpt: str | None = None
    stderr_excerpt: str | None = None


class ReviewDiagnosticCandidate(BaseModel):
    """Represent one bounded candidate-stage finding for run diagnostics."""

    candidate_id: str
    title: str
    file_path: str


class ReviewDiagnosticDroppedCandidate(BaseModel):
    """Represent one bounded dropped-candidate record for run diagnostics."""

    candidate_id: str
    drop_reason: str
    notes: str | None = None


class ReviewDiagnosticCandidateAnnotation(BaseModel):
    """Represent one bounded candidate-annotation record for run diagnostics."""

    candidate_id: str
    flags: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ReviewInlineCommentDecision(BaseModel):
    """Represent one bounded inline-comment decision for rollout diagnostics."""

    finding_identity: str | None = None
    severity: str
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    region_hint: str | None = None
    inline_comments_enabled: bool
    location_trust: Literal["trusted", "weak", "untrusted"]
    existing_inline_comment_found: bool
    anchor_reuse_decision: Literal["reuse", "new", "summary_only"]
    anchor_reuse_reason: str
    authoritative_note_id: int | None = None
    existing_comment_id: str | None = None
    new_comment_id: str | None = None


class ReviewRunDiagnostics(BaseModel):
    """Represent bounded staged-review diagnostics for one internal run."""

    reviewed_head_sha: str
    candidate_findings: list[ReviewDiagnosticCandidate] = Field(default_factory=list)
    forwarded_candidate_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "forwarded_candidate_ids",
            "grounding_accepted_candidate_ids",
        ),
    )
    pre_precision_dropped_candidates: list[ReviewDiagnosticDroppedCandidate] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "pre_precision_dropped_candidates",
            "grounding_dropped_candidates",
        ),
    )
    candidate_annotations: list[ReviewDiagnosticCandidateAnnotation] = Field(default_factory=list)
    precision_accepted_candidate_ids: list[str] = Field(default_factory=list)
    precision_dropped_candidates: list[ReviewDiagnosticDroppedCandidate] = Field(
        default_factory=list
    )
    inline_comment_decisions: list[ReviewInlineCommentDecision] = Field(default_factory=list)
    final_published_finding_summaries: list[str] = Field(default_factory=list)
    final_classification: str


class RunRecord(BaseModel):
    """Represent a single execution record.

    Attributes:
        run_id: Unique execution identifier.
        issue_key: Selected issue key, if any.
        branch_name: Generated branch name, if any.
        commit_sha: Commit SHA after publishing, if any.
        change_request_url: Change request URL after publishing, if any.
        status: Current or final run status.
        started_at: Run start time.
        updated_at: Last update time.
        error_message: Optional error summary.
        failure: Structured failure details when the run fails.
    """

    run_id: str
    issue_key: str | None = None
    work_item_id: str | None = None
    dashboard_item_id: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    change_request_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("change_request_url", "mr_url"),
    )
    status: RunStatus
    started_at: datetime
    updated_at: datetime
    error_message: str | None = None
    failure: FailureDetails | None = None
    review_diagnostics: ReviewRunDiagnostics | None = None

    @property
    def mr_url(self) -> str | None:
        """Return the legacy merge-request URL alias."""
        return self.change_request_url

    @mr_url.setter
    def mr_url(self, value: str | None) -> None:
        """Persist the legacy merge-request URL alias."""
        self.change_request_url = value


class IssueState(BaseModel):
    """Represent the latest known lifecycle state for an issue.

    Attributes:
        status: Latest lifecycle status.
        last_run_id: Most recent run touching the issue.
        branch_name: Generated branch name, if any.
        change_request_url: Change request URL, if any.
        attempt_count: Number of automated attempts made.
        last_error: Most recent error for the issue.
        failure: Structured failure details for the latest failed attempt.
        updated_at: Last update timestamp.
    """

    status: str
    last_run_id: str
    branch_name: str | None = None
    change_request_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("change_request_url", "mr_url"),
    )
    attempt_count: int = 0
    last_error: str | None = None
    failure: FailureDetails | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def mr_url(self) -> str | None:
        """Return the legacy merge-request URL alias."""
        return self.change_request_url

    @mr_url.setter
    def mr_url(self, value: str | None) -> None:
        """Persist the legacy merge-request URL alias."""
        self.change_request_url = value


class PriorReviewFindingState(BaseModel):
    """Represent one bounded persisted prior-review finding summary."""

    identity: str | None = None
    legacy_identity: str | None = None
    summary: str
    severity: str | None = None
    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    title: str | None = None
    symbol: str | None = None
    issue_kind: str | None = None
    region_hint: str | None = None
    inline_comment: PriorReviewInlineCommentState | None = None


class PriorReviewInlineCommentState(BaseModel):
    """Represent persisted inline-comment continuity metadata for one finding."""

    comment_id: str
    comment_url: str | None = None
    status: Literal["published", "shadow", "superseded"]
    anchor_file_path: str
    anchor_line_start: int | None = None
    anchor_line_end: int | None = None


class ChangeRequestReviewState(BaseModel):
    """Represent the latest known review state for one change-request revision."""

    change_request_number: int
    head_sha: str
    status: Literal["no_findings", "findings_present", "manual_review_only"]
    last_run_id: str
    findings_count: int = 0
    summary: str | None = None
    follow_up_lines: list[str] = Field(default_factory=list)
    findings: list[PriorReviewFindingState] = Field(default_factory=list)
    note_id: int | None = None
    note_url: str | None = None
    projection_retry_pending: bool = False
    projection_retry_warning: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class DashboardItemState(BaseModel):
    """Represent the latest known remediation state for one dashboard item."""

    status: str
    last_run_id: str
    branch_name: str | None = None
    commit_sha: str | None = None
    change_request_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("change_request_url", "mr_url"),
    )
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def mr_url(self) -> str | None:
        """Return the legacy merge-request URL alias."""
        return self.change_request_url

    @mr_url.setter
    def mr_url(self, value: str | None) -> None:
        """Persist the legacy merge-request URL alias."""
        self.change_request_url = value


class RemediationExclusionState(BaseModel):
    """Represent one persisted remediation exclusion decision."""

    source: str
    issue_key: str
    scope: str | None = None
    reason: str
    updated_at: datetime = Field(default_factory=utc_now)
    updated_by: str | None = None


class RepositoryState(BaseModel):
    """Represent repository-level state metadata.

    Attributes:
        base_branch: Repository base branch.
        gitlab_project_id: GitLab project ID, if known.
        sonarqube_project_key: SonarQube project key, if known.
    """

    base_branch: str
    gitlab_project_id: str | None = None
    sonarqube_project_key: str | None = None


class AppState(BaseModel):
    """Represent the persisted state file.

    Attributes:
        version: State file version.
        updated_at: Last state update time.
        repository: Repository metadata.
        active_issue_key: Currently locked issue key, if any.
        active_dashboard_item_id: Currently locked dashboard item ID, if any.
        runs: Execution history.
        issues: Latest state keyed by issue key.
        dashboard_items: Latest remediation state keyed by dashboard item ID.
        remediation_exclusions: Operator-managed remediation exclusions.
        reviews: Latest review state keyed by merge-request revision key.
    """

    version: int = 1
    updated_at: datetime = Field(default_factory=utc_now)
    repository: RepositoryState
    active_issue_key: str | None = None
    active_dashboard_item_id: str | None = None
    runs: list[RunRecord] = Field(default_factory=list)
    issues: dict[str, IssueState] = Field(default_factory=dict)
    dashboard_items: dict[str, DashboardItemState] = Field(default_factory=dict)
    remediation_exclusions: list[RemediationExclusionState] = Field(default_factory=list)
    reviews: dict[str, ChangeRequestReviewState] = Field(default_factory=dict)
