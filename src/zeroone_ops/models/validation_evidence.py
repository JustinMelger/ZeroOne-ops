"""Ephemeral evidence for baseline-aware validation; never persisted in work items."""

from dataclasses import dataclass
from typing import Literal


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
