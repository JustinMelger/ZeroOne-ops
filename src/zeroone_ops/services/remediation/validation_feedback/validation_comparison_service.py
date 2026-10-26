"""Assess validation health, correction eligibility, and publication independently."""

from collections import Counter
from dataclasses import replace
from pathlib import PurePosixPath
from typing import Literal

from zeroone_ops.models.analysis import (
    ValidationBaseline,
    ValidationCommandResult,
    ValidationComparison,
    ValidationDiagnostic,
    ValidationOutcome,
    ValidationResult,
)
from zeroone_ops.models.validation_evidence import (
    ParsedValidationOutput,
    SourceChange,
    ToolDiagnostic,
    ValidationAssessment,
    ValidationCommandAssessment,
    ValidationCorrectionDecision,
    ValidationEvidenceProblem,
)
from zeroone_ops.services.remediation.validation_feedback.diagnostic_parser import (
    parse_validation_output,
)
from zeroone_ops.services.remediation.validation_feedback.diagnostic_paths import (
    normalize_diagnostic_paths,
)
from zeroone_ops.services.remediation.validation_feedback.source_line_mapping import (
    unchanged_line_map,
)
from zeroone_ops.services.remediation.validation_feedback.validation_health import command_health


class ValidationComparisonService:
    """Keep publication strict without requiring perfect failure attribution for correction."""

    def compare(
        self,
        *,
        baseline: ValidationBaseline,
        post_edit: ValidationResult,
        files_touched: list[str],
        source_changes: tuple[SourceChange, ...] = (),
        expected_commands: list[str] | None = None,
        repository_root: str | None = None,
    ) -> ValidationComparison:
        """Return the existing publication-shaped result for compatibility consumers."""
        return self.assess(
            baseline=baseline,
            post_edit=post_edit,
            files_touched=files_touched,
            source_changes=source_changes,
            expected_commands=expected_commands,
            repository_root=repository_root,
        ).comparison

    def assess(
        self,
        *,
        baseline: ValidationBaseline,
        post_edit: ValidationResult,
        files_touched: list[str],
        source_changes: tuple[SourceChange, ...] = (),
        expected_commands: list[str] | None = None,
        repository_root: str | None = None,
    ) -> ValidationAssessment:
        """Assess every command; any unusable blocker withholds correction for the whole attempt."""
        problem = _baseline_problem(baseline.result, expected_commands, repository_root)
        problem = problem or _integrity_problem(post_edit, expected_commands, "post_edit")
        if problem is None and [r.command for r in baseline.result.results] != [
            r.command for r in post_edit.results
        ]:
            problem = ValidationEvidenceProblem(
                "post_edit", "Validation command evidence is incomplete or out of order."
            )
        commands = (
            ()
            if problem
            else tuple(
                _assess_command(index, before, after, source_changes, repository_root)
                for index, (before, after) in enumerate(
                    zip(baseline.result.results, post_edit.results, strict=True)
                )
            )
        )
        return _assessment_result(baseline, post_edit, commands, problem, files_touched)


def _integrity_problem(
    result: ValidationResult,
    expected_commands: list[str] | None,
    phase: Literal["baseline", "post_edit"],
) -> ValidationEvidenceProblem | None:
    """Reject missing, reordered, or contradictory evidence before comparing commands."""
    if expected_commands is not None and [r.command for r in result.results] != expected_commands:
        return ValidationEvidenceProblem(
            phase, "Validation command evidence is incomplete or out of order."
        )
    if not result.results or result.passed != all(r.exit_code == 0 for r in result.results):
        return ValidationEvidenceProblem(
            phase, "Validation result evidence is missing or contradictory."
        )
    return None


def _parsed(result: ValidationCommandResult, root: str | None) -> ParsedValidationOutput:
    return normalize_diagnostic_paths(parse_validation_output(result), root)


def _baseline_problem(
    result: ValidationResult,
    expected_commands: list[str] | None,
    root: str | None,
) -> ValidationEvidenceProblem | None:
    problem = _integrity_problem(result, expected_commands, "baseline")
    if problem:
        return problem
    for index, command in enumerate(result.results):
        health = command_health(command)
        parsed = _parsed(command, root)
        if health in {"execution_failure", "unclassified"}:
            reason = (
                "Baseline validation could not execute reliably; repair the validation environment."
            )
        elif not parsed.recognized:
            reason = "Baseline diagnostic evidence or paths are malformed or unsupported."
        elif command.exit_code and parsed.tool is None:
            reason = (
                "Baseline validation failed for an unsupported diagnostic contract; "
                "successful validation is required."
            )
        else:
            continue
        return ValidationEvidenceProblem("baseline", reason, index)
    return None


def _assess_command(
    index: int,
    before: ValidationCommandResult,
    after: ValidationCommandResult,
    changes: tuple[SourceChange, ...],
    root: str | None,
) -> ValidationCommandAssessment:
    health = command_health(after)
    parsed = _parsed(after, root)
    if health in {"execution_failure", "unclassified"}:
        return ValidationCommandAssessment(
            index,
            health,
            False,
            False,
            "Validation could not execute reliably; check the validation environment and output.",
        )
    if not parsed.recognized:
        return ValidationCommandAssessment(
            index,
            "unclassified",
            False,
            False,
            "Validation diagnostic evidence or paths are malformed, unsupported, or contradictory.",
        )
    if health == "passed":
        return ValidationCommandAssessment(index, health, True, False, "Validation passed.")
    if parsed.tool is None:
        return ValidationCommandAssessment(
            index,
            health,
            False,
            before.exit_code == 0,
            "A previously passing command now reports a validation failure; "
            "successful validation is required.",
        )
    introduced = _new_diagnostics(_parsed(before, root), parsed, changes)
    return ValidationCommandAssessment(
        index,
        health,
        not introduced,
        bool(introduced),
        "Validation introduced new diagnostics."
        if introduced
        else "Validation preserved existing diagnostics.",
        introduced,
    )


def _new_diagnostics(
    before: ParsedValidationOutput,
    after: ParsedValidationOutput,
    changes: tuple[SourceChange, ...],
) -> tuple[ToolDiagnostic, ...]:
    mappings = {change.file_path: unchanged_line_map(change) for change in changes}
    original: Counter[ToolDiagnostic] = Counter()
    for diagnostic in before.diagnostics:
        if diagnostic.file_path in mappings:
            line = mappings[diagnostic.file_path].get(diagnostic.line)
            if line is None:
                continue
            diagnostic = replace(diagnostic, line=line)
        original[diagnostic] += 1
    return tuple((Counter(after.diagnostics) - original).elements())


def _assessment_result(
    baseline: ValidationBaseline,
    post_edit: ValidationResult,
    commands: tuple[ValidationCommandAssessment, ...],
    problem: ValidationEvidenceProblem | None,
    files_touched: list[str],
) -> ValidationAssessment:
    allowed = {
        PurePosixPath(path).as_posix()
        for path in files_touched
        if not PurePosixPath(path).is_absolute() and ".." not in PurePosixPath(path).parts
    }
    blockers = tuple(command for command in commands if not command.publication_allowed)
    if problem is None and blockers:
        primary = next((c for c in blockers if not c.correction_eligible), blockers[0])
        problem = ValidationEvidenceProblem("post_edit", primary.reason, primary.index)
    diagnostics = [
        ValidationDiagnostic(
            command=post_edit.results[command.index].command,
            file_path=diagnostic.file_path,
            excerpt=_diagnostic_excerpt(diagnostic),
        )
        for command in commands
        for diagnostic in command.new_diagnostics
        if diagnostic.file_path in allowed
    ]
    outside = any(d.file_path not in allowed for c in commands for d in c.new_diagnostics)
    correction = bool(blockers) and all(c.correction_eligible for c in blockers)
    if not commands or (problem and not blockers):
        correction = False
    outcome: ValidationOutcome
    if problem is None:
        outcome = "passed" if post_edit.passed else "baseline_preserved"
    elif diagnostics and not outside and correction:
        outcome = "actionable_regression"
    else:
        outcome = "unscoped_regression"
    comparison = ValidationComparison(
        outcome=outcome,
        baseline=baseline.result,
        post_edit=post_edit,
        new_relevant_diagnostics=sorted(
            diagnostics, key=lambda d: (d.file_path, d.command, d.excerpt)
        ),
        baseline_failure_count=sum(r.exit_code != 0 for r in baseline.result.results),
        blocking_reason=problem.reason if problem else None,
    )
    reason = (
        "One constrained correction is eligible."
        if correction
        else (problem.reason if problem else "No correction is required.")
    )
    return ValidationAssessment(
        comparison,
        commands,
        ValidationCorrectionDecision(correction, reason, tuple(c.index for c in blockers)),
        problem,
    )


def _diagnostic_excerpt(diagnostic: ToolDiagnostic) -> str:
    location = f"{diagnostic.file_path}:{diagnostic.line}"
    if diagnostic.column is not None:
        location += f":{diagnostic.column}"
    code = f" [{diagnostic.code}]" if diagnostic.code else ""
    return f"{location}: {diagnostic.severity}: {diagnostic.message}{code}"
