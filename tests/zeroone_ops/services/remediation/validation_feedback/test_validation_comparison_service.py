from zeroone_ops.models.analysis import (
    ValidationBaseline,
    ValidationCommandResult,
    ValidationResult,
)
from zeroone_ops.services.remediation.validation_feedback.validation_comparison_service import (
    ValidationComparisonService,
)
from zeroone_ops.services.remediation.validation_feedback.validation_feedback_builder import (
    ValidationFeedbackBuilder,
)


def build_result(*, command: str, exit_code: int, output: str = "") -> ValidationResult:
    return ValidationResult(
        passed=exit_code == 0,
        results=[
            ValidationCommandResult(
                command=command,
                exit_code=exit_code,
                stdout=output,
                stderr="",
                duration_ms=1,
            )
        ],
        summary="validation",
    )


def test_compare_preserves_baseline_failures_without_prompt_feedback() -> None:
    baseline = ValidationBaseline(
        result=build_result(
            command="uv run pytest",
            exit_code=1,
            output="tests/other_test.py: assertion failed",
        )
    )
    comparison = ValidationComparisonService().compare(
        baseline=baseline,
        post_edit=baseline.result,
        files_touched=["src/service.py"],
    )

    assert comparison.outcome == "baseline_preserved"
    assert comparison.allows_publication is True
    assert (
        ValidationFeedbackBuilder().build(
            comparison=comparison,
            files_touched=["src/service.py"],
        )
        is None
    )


def test_compare_blocks_a_changed_baseline_failure_exit_code() -> None:
    baseline = ValidationBaseline(
        result=build_result(
            command="uv run pytest",
            exit_code=1,
            output="tests/other_test.py: assertion failed",
        )
    )
    comparison = ValidationComparisonService().compare(
        baseline=baseline,
        post_edit=build_result(
            command="uv run pytest",
            exit_code=2,
            output="tests/other_test.py: assertion failed",
        ),
        files_touched=["src/service.py"],
    )

    assert comparison.outcome == "unscoped_regression"
    assert comparison.allows_publication is False


def test_compare_marks_new_edited_file_diagnostic_actionable() -> None:
    baseline = ValidationBaseline(result=build_result(command="ruff check .", exit_code=0))
    post_edit = build_result(
        command="ruff check .",
        exit_code=1,
        output="src/service.py:12:1: E999 generated regression",
    )

    comparison = ValidationComparisonService().compare(
        baseline=baseline,
        post_edit=post_edit,
        files_touched=["src/service.py"],
    )

    assert comparison.outcome == "actionable_regression"
    feedback = ValidationFeedbackBuilder().build(
        comparison=comparison,
        files_touched=["src/service.py"],
    )
    assert feedback is not None
    assert feedback.diagnostics[0].file_path == "src/service.py"


def test_compare_blocks_new_diagnostic_outside_editable_file() -> None:
    comparison = ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=build_result(command="uv run pytest", exit_code=0)),
        post_edit=build_result(
            command="uv run pytest",
            exit_code=1,
            output="tests/other_test.py: assertion failed",
        ),
        files_touched=["src/service.py"],
    )

    assert comparison.outcome == "unscoped_regression"
    assert comparison.new_relevant_diagnostics == []


def test_compare_blocks_mixed_scoped_and_unscoped_regressions() -> None:
    comparison = ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=build_result(command="ruff check .", exit_code=0)),
        post_edit=build_result(
            command="ruff check .",
            exit_code=1,
            output=(
                "src/service.py:1:1: E999 scoped regression\n"
                "tests/other_test.py:1:1: E999 unscoped regression"
            ),
        ),
        files_touched=["src/service.py"],
    )

    assert comparison.outcome == "unscoped_regression"
    assert comparison.new_relevant_diagnostics[0].file_path == "src/service.py"


def test_compare_blocks_mixed_scoped_and_escaping_path_regressions() -> None:
    comparison = ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=build_result(command="ruff check .", exit_code=0)),
        post_edit=build_result(
            command="ruff check .",
            exit_code=1,
            output=(
                "src/service.py:1:1: E999 scoped regression\n"
                "../src/other.py:1:1: E999 escaping regression"
            ),
        ),
        files_touched=["src/service.py"],
    )

    assert comparison.outcome == "unscoped_regression"


def test_compare_requires_an_exact_safe_diagnostic_path() -> None:
    comparison = ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=build_result(command="ruff check .", exit_code=0)),
        post_edit=build_result(
            command="ruff check .",
            exit_code=1,
            output="src/service.py.backup:1:1: E999 unrelated file",
        ),
        files_touched=["src/service.py"],
    )

    assert comparison.outcome == "unscoped_regression"
    assert comparison.new_relevant_diagnostics == []


def test_compare_rejects_unsafe_paths_and_subtracts_baseline_lines() -> None:
    baseline = ValidationBaseline(
        result=build_result(
            command="ruff check .",
            exit_code=1,
            output="src/service.py:1:1: E999 known failure",
        )
    )
    comparison = ValidationComparisonService().compare(
        baseline=baseline,
        post_edit=build_result(
            command="ruff check .",
            exit_code=1,
            output=(
                "src/service.py:1:1: E999 known failure\n../src/service.py:2:1: E999 unsafe path"
            ),
        ),
        files_touched=["src/service.py"],
    )

    assert comparison.outcome == "unscoped_regression"
    assert comparison.new_relevant_diagnostics == []


def test_feedback_builder_limits_the_rendered_packet_length() -> None:
    comparison = ValidationComparisonService().compare(
        baseline=ValidationBaseline(result=build_result(command="ruff check .", exit_code=0)),
        post_edit=build_result(
            command="ruff check .",
            exit_code=1,
            output="src/service.py:1:1: E999 " + "x" * 10_000,
        ),
        files_touched=["src/service.py"],
    )

    feedback = ValidationFeedbackBuilder().build(
        comparison=comparison,
        files_touched=["src/service.py"],
    )

    assert feedback is not None
    rendered = "\n".join(
        [
            "Allowed files: " + ", ".join(f"`{path}`" for path in feedback.allowed_file_paths),
            "New diagnostics:",
            *[
                f"- `{diagnostic.file_path}` via `{diagnostic.command}`: {diagnostic.excerpt}"
                for diagnostic in feedback.diagnostics
            ],
        ]
    )
    assert len(rendered) <= 4_000
