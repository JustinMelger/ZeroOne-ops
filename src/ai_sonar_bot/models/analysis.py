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
