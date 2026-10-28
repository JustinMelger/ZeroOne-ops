import pytest

from zeroone_ops.models.analysis import (
    ValidationBaseline,
    ValidationCommandResult,
    ValidationResult,
)
from zeroone_ops.models.validation_evidence import SourceChange
from zeroone_ops.services.remediation.validation_feedback.diagnostic_parser import (
    parse_validation_output,
    validation_tool,
)
from zeroone_ops.services.remediation.validation_feedback.source_line_mapping import (
    unchanged_line_map,
)
from zeroone_ops.services.remediation.validation_feedback.validation_comparison_service import (
    ValidationComparisonService,
)


def result(output: str, *, code: int = 1, command: str = "uv run mypy src") -> ValidationResult:
    return ValidationResult(
        passed=code == 0,
        results=[
            ValidationCommandResult(
                command=command, exit_code=code, stdout=output, stderr="", duration_ms=1
            )
        ],
        summary="validation",
    )


def compare(
    before: str,
    after: str,
    *,
    changes: tuple[SourceChange, ...] = (),
    command: str = "uv run mypy src",
):
    return ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=result(before, command=command)),
        post_edit=result(after, command=command),
        files_touched=["src/app.py"],
        source_changes=changes,
    )


def test_import_removal_relocates_unchanged_mypy_diagnostic() -> None:
    change = SourceChange(
        "src/app.py", "import os\n\ndef demo():\n    return 1\n", "\ndef demo():\n    return 1\n"
    )
    comparison = compare(
        "src/app.py:3: error: Missing annotation  [no-untyped-def]\n"
        "Found 1 error in 1 file (checked 2 source files)",
        "src/app.py:2: error: Missing annotation  [no-untyped-def]\n"
        "Found 1 error in 1 file (checked 2 source files)",
        changes=(change,),
    )
    assert comparison.outcome == "baseline_preserved"
    assert comparison.baseline_failure_count == 1


def test_removed_errors_and_changed_summary_are_an_improvement() -> None:
    first = "src/app.py:3: error: Missing annotation  [no-untyped-def]"
    second = "src/other.py:7: error: Missing annotation  [no-untyped-def]"
    comparison = compare(
        first + "\n" + second + "\nFound 2 errors in 2 files (checked 2 source files)",
        second + "\nFound 1 error in 1 file (checked 2 source files)",
    )
    assert comparison.allows_publication


@pytest.mark.parametrize(
    "after",
    [
        "src/app.py:3: error: Missing annotation  [attr-defined]",
        "src/app.py:3: error: Different error  [no-untyped-def]",
        "src/app.py:3: error: Missing annotation  [no-untyped-def]\n"
        "src/app.py:3: error: Missing annotation  [no-untyped-def]",
    ],
)
def test_new_codes_messages_and_occurrences_remain_failures(after: str) -> None:
    comparison = compare("src/app.py:3: error: Missing annotation  [no-untyped-def]", after)
    assert comparison.outcome == "actionable_regression"
    assert len(comparison.new_relevant_diagnostics) == 1


@pytest.mark.parametrize(
    "change, expected",
    [
        (SourceChange("src/app.py", "a\nb\nc\nd\n", "new\na\nb\nc\nd\n"), {1: 2, 2: 3, 3: 4, 4: 5}),
        (SourceChange("src/app.py", "a\nb\nc\nd\n", "a\nx\nc\ny\nd\n"), {1: 1, 3: 3, 4: 5}),
        (SourceChange("src/app.py", "same\nsame\nend\n", "same\nend\n"), {3: 2}),
        (SourceChange("src/app.py", "a\n", "changed\n"), {}),
        (SourceChange("src/app.py", None, "a\n"), {}),
        (SourceChange("src/app.py", "same\nsame\n", "same\nsame\n"), {1: 1, 2: 2}),
        (SourceChange("src/app.py", "a\fb\nlast\n", "new\na\fb\nlast\n"), {1: 2, 2: 3}),
    ],
)
def test_line_mapping_uses_actual_unchanged_unambiguous_source(
    change: SourceChange, expected: dict[int, int]
) -> None:
    assert unchanged_line_map(change) == expected


def test_columns_and_modified_lines_are_not_erased() -> None:
    before = "src/app.py:1:4: error: Bad value  [assignment]"
    assert (
        compare(before, before, changes=(SourceChange("src/app.py", "old", "new"),)).outcome
        == "actionable_regression"
    )
    assert compare(before, before.replace(":4:", ":5:")).outcome == "actionable_regression"
    assert compare(before, before.replace(":1:", ":2:")).outcome == "actionable_regression"


@pytest.mark.parametrize("code", [2, 124, 126, 127, -9, 137])
def test_operational_failures_never_preserve_a_baseline(code: int) -> None:
    failed = result("tool failed", code=code)
    comparison = ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=failed), post_edit=failed, files_touched=["src/app.py"]
    )
    assert comparison.outcome == "unscoped_regression"
    assert not comparison.allows_publication


def test_successful_validation_after_a_diagnostic_baseline() -> None:
    comparison = ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=result("src/app.py:1: error: Bad value  [assignment]")),
        post_edit=result("Success: no issues found in 1 source file", code=0),
        files_touched=["src/app.py"],
    )
    assert comparison.outcome == "passed"


@pytest.mark.parametrize(
    "output",
    [
        "Found 1 error in 1 file (checked 2 source files)",
        "src/app.py:1: error: Bad value\nUnexpected plugin warning",
        "src/app.py:0: error: Bad value",
        "src/app.py:1: error: Bad value\nFound 0 errors in 1 file (checked 1 source file)",
        "src/app.py:1: error: Bad value\nSuccess: no issues found in 1 source file",
    ],
)
def test_incomplete_or_unexpected_output_cannot_be_preserved(output: str) -> None:
    assert not compare(output, output).allows_publication


@pytest.mark.parametrize(
    "command, output",
    [
        (
            "uv run mypy src",
            "src/app.py:3: error: Bad value  [assignment]\nsrc/app.py:3: note: explanation\n"
            "Found 1 error in 1 file (checked 1 source file)",
        ),
        (
            "ruff check src",
            "src/app.py:3:8: F401 [*] `os` imported but unused\nFound 1 error.\n"
            "[*] 1 fixable with the `--fix` option.",
        ),
        (
            "uv run ruff check src",
            "F401 [*] `os` imported but unused\n --> src/app.py:3:8\n  |\n3 | import os\n"
            "  |        ^^\n  |\nhelp: Remove unused import: `os`\n"
            "  |\n  - import os\n3 +\n4 | value = 1\n  |\n"
            "Found 1 error.\n[*] 1 fixable with `--fix`.",
        ),
    ],
)
def test_supported_tool_output_keeps_diagnostic_evidence(command: str, output: str) -> None:
    parsed = parse_validation_output(result(output, command=command).results[0])
    assert parsed.recognized
    assert len(parsed.diagnostics) == 1
    assert parsed.diagnostics[0].file_path == "src/app.py"
    assert compare(output, output, command=command).outcome == "baseline_preserved"


def test_unsupported_commands_require_exact_output_including_occurrences() -> None:
    assert compare("failed\nfailed", "failed", command="pytest").outcome == "unscoped_regression"
    assert compare("failed", "failed", command="pytest").outcome == "unscoped_regression"


@pytest.mark.parametrize(
    "post",
    [
        ValidationResult(passed=True, results=[], summary="incomplete"),
        result("src/app.py:1: error: Bad value").model_copy(update={"passed": True}),
        result("failure", command="other"),
    ],
)
def test_missing_contradictory_or_different_command_results_block(post: ValidationResult) -> None:
    comparison = ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=result("src/app.py:1: error: Bad value")),
        post_edit=post,
        files_touched=["src/app.py"],
    )
    assert not comparison.allows_publication


def test_ordered_complete_command_sequence_is_required_even_for_success() -> None:
    baseline = result("", code=0)
    post = baseline.model_copy(deep=True)
    comparison = ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=baseline),
        post_edit=post,
        files_touched=["src/app.py"],
        expected_commands=["uv run mypy src", "ruff check src"],
    )
    assert not comparison.allows_publication


def test_unavailable_baseline_cannot_authorize_later_clean_validation() -> None:
    comparison = ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=result("tool missing", code=127)),
        post_edit=result("", code=0),
        files_touched=["src/app.py"],
    )
    assert not comparison.allows_publication


def test_unknown_command_summaries_are_not_filtered() -> None:
    comparison = compare("Found 2 errors.", "Found 1 error.", command="custom-linter")
    assert not comparison.allows_publication


def test_ambiguous_relocation_never_consumes_an_existing_diagnostic() -> None:
    comparison = compare(
        "src/app.py:2: error: Bad value  [assignment]",
        "src/app.py:1: error: Bad value  [assignment]",
        changes=(SourceChange("src/app.py", "repeat\nrepeat\n", "repeat\n"),),
    )
    assert comparison.outcome == "actionable_regression"


def test_mypy_global_notes_and_ruff_syntax_diagnostics() -> None:
    mypy = "src/app.py: note: In function demo:\nsrc/app.py:1: error: Bad value  [assignment]"
    assert compare(mypy, mypy).allows_publication
    ruff = "src/app.py:1:8: invalid-syntax Expected an expression\nFound 1 error."
    assert compare(ruff, ruff, command="ruff check src").allows_publication


def test_ruff_does_not_discard_arbitrary_diff_like_output_without_fix_context() -> None:
    output = "F401 Unused import\n --> src/app.py:1:1\n- unexpected tool failure"
    assert not compare(output, output, command="ruff check src").allows_publication


@pytest.mark.parametrize(
    "command, expected",
    [
        ("uv run --no-sync --group dev mypy src", "mypy"),
        ("/usr/bin/uv run --locked --group=dev ruff check src", "ruff"),
        ("uv run -- python3.13 -m mypy src", "mypy"),
        ("ruff format --check .", None),
        ("mypy src || true", None),
        ("echo mypy", None),
    ],
)
def test_only_supported_executable_invocations_use_tool_parsers(command, expected) -> None:
    assert validation_tool(command) == expected
