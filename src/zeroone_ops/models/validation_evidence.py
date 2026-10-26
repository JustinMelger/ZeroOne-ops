"""Ephemeral evidence for baseline-aware validation; never persisted in work items."""

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.analysis import ValidationComparison


@dataclass(frozen=True)
class SourceChange:
    """Actual source contents on either side of one validation attempt."""

    file_path: str
    before: str | None
    after: str | None


@dataclass(frozen=True)
class ToolDiagnostic:
    """One diagnostic occurrence, including its original location and wording."""

    file_path: str
    line: int
    column: int | None
    severity: str
    code: str | None
    message: str


@dataclass(frozen=True)
class ParsedValidationOutput:
    """Complete parsed output, or an explicit unsupported/unrecognized result."""

    tool: Literal["mypy", "ruff"] | None
    diagnostics: tuple[ToolDiagnostic, ...] = ()
    recognized: bool = True


@dataclass(frozen=True)
class ValidationCommandAssessment:
    """Independent publication and correction decisions for one ordered command."""

    index: int
    health: Literal["passed", "validation_failure", "execution_failure", "unclassified"]
    publication_allowed: bool
    correction_eligible: bool
    reason: str
    new_diagnostics: tuple[ToolDiagnostic, ...] = ()


@dataclass(frozen=True)
class ValidationCorrectionDecision:
    """Whether every blocking command permits one constrained correction."""

    eligible: bool
    reason: str
    command_indices: tuple[int, ...] = ()


@dataclass(frozen=True)
class ValidationEvidenceProblem:
    """Unusable evidence, correlated with its phase and command when known."""

    phase: Literal["baseline", "post_edit"]
    reason: str
    command_index: int | None = None


@dataclass(frozen=True)
class ValidationAssessment:
    """Final publication result plus an independent, bounded correction decision."""

    comparison: ValidationComparison
    commands: tuple[ValidationCommandAssessment, ...]
    correction: ValidationCorrectionDecision
    problem: ValidationEvidenceProblem | None = None
