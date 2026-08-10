"""Compare bounded remediation validation evidence."""

from __future__ import annotations

from pathlib import PurePosixPath

from zeroone_ops.models.analysis import (
    ValidationBaseline,
    ValidationCommandResult,
    ValidationComparison,
    ValidationDiagnostic,
    ValidationOutcome,
    ValidationResult,
)


class ValidationComparisonService:
    """Classify post-edit validation relative to a pre-edit baseline."""

    def compare(
        self,
        *,
        baseline: ValidationBaseline,
        post_edit: ValidationResult,
        files_touched: list[str],
    ) -> ValidationComparison:
        """Return the deterministic bounded outcome for one patch attempt."""
        allowed_paths = _normalized_paths(files_touched)
        diagnostics: list[ValidationDiagnostic] = []
        has_new_failure = False
        has_unscoped_regression = False
        baseline_results = baseline.result.results

        for index, post_result in enumerate(post_edit.results):
            baseline_result = _matching_baseline_result(
                baseline_results=baseline_results,
                index=index,
                command=post_result.command,
            )
            if post_result.exit_code == 0:
                continue
            baseline_lines = _result_lines(baseline_result)
            post_lines = _result_lines(post_result)
            new_lines = sorted(post_lines - baseline_lines)
            exit_code_changed = (
                baseline_result is not None
                and baseline_result.exit_code != 0
                and baseline_result.exit_code != post_result.exit_code
            )
            if baseline_result is None or baseline_result.exit_code == 0 or new_lines:
                has_new_failure = True
            line_diagnostics, has_unscoped_diagnostic = _diagnostics_for_lines(
                command=post_result.command,
                lines=new_lines,
                allowed_paths=allowed_paths,
            )
            diagnostics.extend(line_diagnostics)
            has_unscoped_regression = (
                has_unscoped_regression
                or baseline_result is None
                or exit_code_changed
                or has_unscoped_diagnostic
            )

        diagnostics.sort(key=lambda item: (item.file_path, item.command, item.excerpt))
        outcome: ValidationOutcome
        if post_edit.passed:
            outcome = "passed"
        elif has_unscoped_regression:
            outcome = "unscoped_regression"
        elif diagnostics:
            outcome = "actionable_regression"
        elif has_new_failure:
            outcome = "unscoped_regression"
        else:
            outcome = "baseline_preserved"
        return ValidationComparison(
            outcome=outcome,
            baseline=baseline.result,
            post_edit=post_edit,
            new_relevant_diagnostics=diagnostics,
            baseline_failure_count=sum(result.exit_code != 0 for result in baseline.result.results),
        )


def _matching_baseline_result(
    *,
    baseline_results: list[ValidationCommandResult],
    index: int,
    command: str,
) -> ValidationCommandResult | None:
    """Return the same-position baseline result only when its command agrees."""
    if index >= len(baseline_results):
        return None
    result = baseline_results[index]
    return result if result.command == command else None


def _normalized_paths(paths: list[str]) -> tuple[str, ...]:
    """Return safe normalized repository-relative paths."""
    normalized: list[str] = []
    for path in paths:
        candidate = PurePosixPath(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            continue
        normalized.append(candidate.as_posix())
    return tuple(sorted(set(normalized)))


def _result_lines(result: ValidationCommandResult | None) -> set[str]:
    """Return normalized non-empty output lines for one command result."""
    if result is None:
        return set()
    return {
        line.strip()
        for output in (result.stdout, result.stderr)
        for line in output.splitlines()
        if line.strip()
    }


def _diagnostics_for_lines(
    *,
    command: str,
    lines: list[str],
    allowed_paths: tuple[str, ...],
) -> tuple[list[ValidationDiagnostic], bool]:
    """Extract allowed-file diagnostics and flag safe paths outside the scope."""
    diagnostics: list[ValidationDiagnostic] = []
    has_unscoped_diagnostic = False
    for line in lines:
        diagnostic_path, has_unsafe_path = _diagnostic_path(
            line,
            allowed_paths=allowed_paths,
        )
        if has_unsafe_path:
            has_unscoped_diagnostic = True
        if diagnostic_path is None:
            continue
        if diagnostic_path not in allowed_paths:
            has_unscoped_diagnostic = True
            continue
        diagnostics.append(
            ValidationDiagnostic(
                command=command,
                file_path=diagnostic_path,
                excerpt=line,
            )
        )
    return diagnostics, has_unscoped_diagnostic


def _diagnostic_path(
    line: str,
    *,
    allowed_paths: tuple[str, ...],
) -> tuple[str | None, bool]:
    """Extract a diagnostic path and flag malformed path-like prefixes."""
    path_text, separator, _ = line.partition(":")
    raw_path = path_text.strip()
    if not separator or not raw_path:
        return None, False
    candidate = PurePosixPath(path_text.strip())
    if candidate.is_absolute() or ".." in candidate.parts:
        return None, _looks_like_path(raw_path)
    normalized_path = candidate.as_posix()
    if normalized_path == ".":
        return None, False
    if normalized_path in allowed_paths or "/" in raw_path or candidate.suffix:
        return normalized_path, False
    return None, False


def _looks_like_path(value: str) -> bool:
    """Return whether a malformed prefix plausibly names a file path."""
    return "/" in value or value.startswith(".")
