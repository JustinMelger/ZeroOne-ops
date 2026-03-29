"""State models.

This module defines the JSON-backed application state used to track runs and
issue lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


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
    MANUAL = "manual"
    FAILED = "failed"


class FailureStage(StrEnum):
    """Enumerate execution stages that can fail."""

    ISSUE_INTAKE = "issue_intake"
    ANALYSIS = "analysis"
    PATCH_APPLY = "patch_apply"
    VALIDATION = "validation"
    BRANCH_PREPARATION = "branch_preparation"
    COMMIT = "commit"
    PUBLISH = "publish"


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


class RunRecord(BaseModel):
    """Represent a single execution record.

    Attributes:
        run_id: Unique execution identifier.
        issue_key: Selected issue key, if any.
        branch_name: Generated branch name, if any.
        commit_sha: Commit SHA after publishing, if any.
        mr_url: Merge request URL after publishing, if any.
        status: Current or final run status.
        started_at: Run start time.
        updated_at: Last update time.
        error_message: Optional error summary.
        failure: Structured failure details when the run fails.
    """

    run_id: str
    issue_key: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    mr_url: str | None = None
    status: RunStatus
    started_at: datetime
    updated_at: datetime
    error_message: str | None = None
    failure: FailureDetails | None = None


class IssueState(BaseModel):
    """Represent the latest known lifecycle state for an issue.

    Attributes:
        status: Latest lifecycle status.
        last_run_id: Most recent run touching the issue.
        branch_name: Generated branch name, if any.
        mr_url: Merge request URL, if any.
        attempt_count: Number of automated attempts made.
        last_error: Most recent error for the issue.
        failure: Structured failure details for the latest failed attempt.
        updated_at: Last update timestamp.
    """

    status: str
    last_run_id: str
    branch_name: str | None = None
    mr_url: str | None = None
    attempt_count: int = 0
    last_error: str | None = None
    failure: FailureDetails | None = None
    updated_at: datetime = Field(default_factory=utc_now)


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
        runs: Execution history.
        issues: Latest state keyed by issue key.
    """

    version: int = 1
    updated_at: datetime = Field(default_factory=utc_now)
    repository: RepositoryState
    active_issue_key: str | None = None
    runs: list[RunRecord] = Field(default_factory=list)
    issues: dict[str, IssueState] = Field(default_factory=dict)
