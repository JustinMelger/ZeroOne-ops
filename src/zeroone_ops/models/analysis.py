"""Analysis and validation models.

This module contains typed objects returned by the analysis, patch generation,
and validation phases.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

type ValidationOutcome = Literal[
    "passed",
    "baseline_preserved",
    "actionable_regression",
    "unscoped_regression",
]
type RemediationIntent = Literal["fix", "chore"]


class AnalysisClassification(StrEnum):
    """Classify how safely an issue can be handled automatically."""

    AUTO_FIXABLE = "auto_fixable"
    RETRYABLE = "retryable"
    MANUAL = "manual"


class IssueAnalysis(BaseModel):
    """Represent structured issue analysis.

    Attributes:
        issue_key: SonarQube issue key.
        classification: Automation suitability classification.
        summary: Short analysis summary.
        risk_notes: Known risks or caveats.
        target_files: Files expected to change.
        proposed_strategy: High-level fix approach.
    """

    issue_key: str
    classification: AnalysisClassification
    summary: str
    risk_notes: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    proposed_strategy: str
    remediation_intent: RemediationIntent = "chore"


class CodeContextSnippet(BaseModel):
    """Represent a focused source-code snippet.

    Attributes:
        start_line: First included source line number.
        end_line: Last included source line number.
        content: Source content with line-number prefixes.
    """

    start_line: int
    end_line: int
    content: str


class PriorReviewFeedback(BaseModel):
    """Represent bounded prior review feedback for a remediation retry."""

    review_status: str
    review_findings_count: int | None = None
    review_feedback_summary: str | None = None
    review_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    review_confidence_reason: str | None = None
    reviewed_head_sha: str | None = None
    retry_count: int | None = None


class RepositoryGuidanceContext(BaseModel):
    """Represent one bounded repository guidance excerpt."""

    file_path: str
    summary: str


class ValidationDiagnostic(BaseModel):
    """Represent one bounded validation diagnostic relevant to a patch."""

    command: str
    file_path: str
    excerpt: str


class ValidationBaseline(BaseModel):
    """Represent validation evidence captured before applying a patch."""

    result: ValidationResult


class ValidationComparison(BaseModel):
    """Compare baseline and post-edit validation evidence."""

    outcome: ValidationOutcome
    baseline: ValidationResult
    post_edit: ValidationResult
    new_relevant_diagnostics: list[ValidationDiagnostic] = Field(default_factory=list)
    baseline_failure_count: int = Field(ge=0)

    @property
    def allows_publication(self) -> bool:
        """Return whether the comparison permits bounded publication."""
        return self.outcome in {"passed", "baseline_preserved"}


class ValidationFeedback(BaseModel):
    """Represent the bounded validator evidence supplied to one retry."""

    allowed_file_paths: list[str] = Field(default_factory=list)
    diagnostics: list[ValidationDiagnostic] = Field(default_factory=list)


class IssueContext(BaseModel):
    """Represent structured source context for a selected issue.

    Attributes:
        issue_key: SonarQube issue key.
        file_path: Repository-relative file path for the issue.
        line: Issue line number if provided by SonarQube.
        file_size_bytes: Size of the source file in bytes.
        snippet: Focused source snippet around the issue line.
        full_file_included: Whether the returned content covers the whole file.
        truncated: Whether context had to be truncated due to file size rules.
    """

    issue_key: str
    file_path: str
    line: int | None = None
    file_size_bytes: int
    snippet: CodeContextSnippet
    full_file_included: bool
    truncated: bool
    repository_guidance: list[RepositoryGuidanceContext] = Field(default_factory=list)
    prior_review_feedback: PriorReviewFeedback | None = None
    validation_feedback: ValidationFeedback | None = None
    remediation_intent: RemediationIntent | None = None


class PatchProposal(BaseModel):
    """Represent a proposed code patch.

    Attributes:
        issue_key: SonarQube issue key.
        files_touched: Files modified by the patch.
        unified_diff: Unified diff to apply.
        commit_message: Proposed commit message.
        change_request_title: Proposed change request title.
        change_request_description: Proposed change request description.
    """

    issue_key: str
    files_touched: list[str] = Field(default_factory=list)
    unified_diff: str
    commit_message: str
    change_request_title: str = Field(
        validation_alias=AliasChoices("change_request_title", "mr_title")
    )
    change_request_description: str = Field(
        validation_alias=AliasChoices("change_request_description", "mr_description")
    )
    remediation_intent: RemediationIntent = "chore"

    @property
    def mr_title(self) -> str:
        """Return the legacy merge-request title alias."""
        return self.change_request_title

    @property
    def mr_description(self) -> str:
        """Return the legacy merge-request description alias."""
        return self.change_request_description


class TextEdit(BaseModel):
    """Represent one exact text replacement in a repository file.

    Attributes:
        file_path: Repository-relative file path to edit.
        search_text: Exact existing text that should be replaced.
        replace_text: Replacement text to apply.
        line_hint: Optional 1-based line hint used to disambiguate repeated matches.
    """

    file_path: str
    search_text: str
    replace_text: str
    line_hint: int | None = None


class StructuredEditProposal(BaseModel):
    """Represent a structured edit plan that the bot can render to a diff.

    Attributes:
        issue_key: SonarQube issue key.
        edits: Exact text edits to apply.
        commit_message: Proposed commit message.
        change_request_title: Proposed change request title.
        change_request_description: Proposed change request description.
    """

    issue_key: str
    edits: list[TextEdit] = Field(default_factory=list)
    commit_message: str
    change_request_title: str = Field(
        validation_alias=AliasChoices("change_request_title", "mr_title")
    )
    change_request_description: str = Field(
        validation_alias=AliasChoices("change_request_description", "mr_description")
    )
    remediation_intent: RemediationIntent = "chore"

    @property
    def mr_title(self) -> str:
        """Return the legacy merge-request title alias."""
        return self.change_request_title

    @property
    def mr_description(self) -> str:
        """Return the legacy merge-request description alias."""
        return self.change_request_description


class ValidationCommandResult(BaseModel):
    """Capture the result of a single validation command.

    Attributes:
        command: Executed shell command.
        exit_code: Process exit code.
        stdout: Captured standard output.
        stderr: Captured standard error.
        duration_ms: Runtime in milliseconds.
    """

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


class ValidationResult(BaseModel):
    """Represent aggregate validation status.

    Attributes:
        passed: Whether all commands succeeded.
        results: Individual command results.
        summary: Short human-readable outcome.
    """

    passed: bool
    results: list[ValidationCommandResult] = Field(default_factory=list)
    summary: str
