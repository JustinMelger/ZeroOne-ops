"""Compare bounded remediation validation evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import PurePosixPath

from zeroone_ops.models.analysis import (
    ValidationBaseline,
    ValidationCommandResult,
    ValidationComparison,
    ValidationDiagnostic,
    ValidationOutcome,
    ValidationResult,
)
from zeroone_ops.models.validation_evidence import SourceChange, ToolDiagnostic
from zeroone_ops.services.remediation.validation_feedback.diagnostic_parser import (
    execution_failure,
    parse_validation_output,
)
from zeroone_ops.services.remediation.validation_feedback.source_line_mapping import (
    unchanged_line_map,
)


class ValidationComparisonService:
    """Classify post-edit validation relative to a pre-edit baseline."""

    def compare(
        self,
        *,
        baseline: ValidationBaseline,
        post_edit: ValidationResult,
        files_touched: list[str],
        source_changes: tuple[SourceChange, ...] = (),
        expected_commands: list[str] | None = None,
    ) -> ValidationComparison:
        """Return the deterministic bounded outcome for one patch attempt."""
        allowed_paths = _normalized_paths(files_touched)
        diagnostics: list[ValidationDiagnostic] = []
        blocking_reason = validation_evidence_failure(baseline.result, expected_commands)
        blocking_reason = blocking_reason or validation_evidence_failure(
            post_edit, expected_commands
        )
        baseline_results = baseline.result.results
        if [r.command for r in baseline_results] != [r.command for r in post_edit.results]:
            blocking_reason = "Validation command evidence is incomplete or out of order."

        if blocking_reason is None:
            for before, after in zip(baseline_results, post_edit.results, strict=True):
                new_diagnostics, reason = _compare_command(
                    before, after, allowed_paths, source_changes
                )
                diagnostics.extend(new_diagnostics)
                blocking_reason = blocking_reason or reason

        diagnostics.sort(key=lambda item: (item.file_path, item.command, item.excerpt))
        outcome: ValidationOutcome
        if blocking_reason is not None:
            outcome = "unscoped_regression"
        elif post_edit.passed:
            outcome = "passed"
        elif diagnostics:
            outcome = "actionable_regression"
        else:
            outcome = "baseline_preserved"
        return ValidationComparison(
            outcome=outcome,
            baseline=baseline.result,
            post_edit=post_edit,
            new_relevant_diagnostics=diagnostics,
            baseline_failure_count=sum(result.exit_code != 0 for result in baseline.result.results),
            blocking_reason=blocking_reason,
        )


def validation_evidence_failure(
    result: ValidationResult, expected_commands: list[str] | None = None
) -> str | None:
    """Reject incomplete, contradictory, operational, or unrecognized tool evidence."""
    if expected_commands is not None and [r.command for r in result.results] != expected_commands:
        return "Validation command evidence is incomplete or out of order."
    if not result.results or result.passed != all(r.exit_code == 0 for r in result.results):
        return "Validation result evidence is missing or contradictory."
    for command_result in result.results:
        if execution_failure(command_result):
            return (
                "Validation tooling could not execute reliably; repair the validation environment."
            )
        if not parse_validation_output(command_result).recognized:
            return "Validation tool output is malformed, unsupported, or contradictory."
        if command_result.exit_code != 0 and not (
            command_result.stdout.strip() or command_result.stderr.strip()
        ):
            return "Failed validation has no diagnostic evidence."
    return None


def _compare_command(
    before: ValidationCommandResult,
    after: ValidationCommandResult,
    allowed_paths: tuple[str, ...],
    source_changes: tuple[SourceChange, ...],
) -> tuple[list[ValidationDiagnostic], str | None]:
    """Use structured multisets for supported tools, exact evidence otherwise."""
    parsed_before = parse_validation_output(before)
    parsed_after = parse_validation_output(after)
    if parsed_after.tool is None:
        if after.exit_code == 0:
            return [], None
        if before.exit_code == after.exit_code and (before.stdout, before.stderr) == (
            after.stdout,
            after.stderr,
        ):
            return [], None
        return (
            [],
            "Validation changed for an unsupported command; exact baseline evidence is required.",
        )

    original: Counter[ToolDiagnostic] = Counter()
    changes = {change.file_path: change for change in source_changes}
    mappings = {path: unchanged_line_map(change) for path, change in changes.items()}
    for diagnostic in parsed_before.diagnostics:
        if diagnostic.file_path in mappings:
            relocated_line = mappings[diagnostic.file_path].get(diagnostic.line)
            if relocated_line is None:
                continue
            diagnostic = replace(diagnostic, line=relocated_line)
        original[diagnostic] += 1

    introduced = Counter(parsed_after.diagnostics) - original
    feedback: list[ValidationDiagnostic] = []
    reason = None
    for diagnostic, count in introduced.items():
        if diagnostic.file_path not in allowed_paths:
            reason = "Validation introduced diagnostics outside the one-file repair boundary."
            continue
        excerpt = f"{diagnostic.file_path}:{diagnostic.line}"
        if diagnostic.column is not None:
            excerpt += f":{diagnostic.column}"
        excerpt += f": {diagnostic.severity}: {diagnostic.message}"
        if diagnostic.code:
            excerpt += f" [{diagnostic.code}]"
        feedback.extend(
            ValidationDiagnostic(
                command=after.command, file_path=diagnostic.file_path, excerpt=excerpt
            )
            for _ in range(count)
        )
    return feedback, reason


def _normalized_paths(paths: list[str]) -> tuple[str, ...]:
    """Return safe normalized repository-relative paths."""
    normalized: list[str] = []
    for path in paths:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            continue
        normalized.append(candidate.as_posix())
    return tuple(sorted(set(normalized)))
