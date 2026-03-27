"""Analysis and validation models.

This module contains typed objects returned by the analysis, patch generation,
and validation phases.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


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


class PatchProposal(BaseModel):
    """Represent a proposed code patch.

    Attributes:
        issue_key: SonarQube issue key.
        files_touched: Files modified by the patch.
        unified_diff: Unified diff to apply.
        commit_message: Proposed commit message.
        mr_title: Proposed merge request title.
        mr_description: Proposed merge request description.
    """

    issue_key: str
    files_touched: list[str] = Field(default_factory=list)
    unified_diff: str
    commit_message: str
    mr_title: str
    mr_description: str


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
