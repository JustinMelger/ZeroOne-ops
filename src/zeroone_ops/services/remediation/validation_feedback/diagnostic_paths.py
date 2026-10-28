"""Normalize scanner locations without filesystem access or guessed working directories."""

from dataclasses import replace
from pathlib import PurePosixPath

from zeroone_ops.models.validation_evidence import ParsedValidationOutput


def normalize_diagnostic_paths(
    output: ParsedValidationOutput, repository_root: str | None
) -> ParsedValidationOutput:
    """Reject paths that cannot be proven to name repository-relative evidence."""
    normalized = []
    root = PurePosixPath(repository_root) if repository_root else None
    for diagnostic in output.diagnostics:
        path = PurePosixPath(diagnostic.file_path)
        if ".." in path.parts or "\\" in diagnostic.file_path:
            return replace(output, recognized=False, failure_kind="unresolved_path")
        if path.is_absolute():
            if root is None or not root.is_absolute() or not path.is_relative_to(root):
                return replace(output, recognized=False, failure_kind="unresolved_path")
            path = path.relative_to(root)
        if path.as_posix() == ".":
            return replace(output, recognized=False, failure_kind="unresolved_path")
        normalized.append(replace(diagnostic, file_path=path.as_posix()))
    return replace(output, diagnostics=tuple(normalized))
