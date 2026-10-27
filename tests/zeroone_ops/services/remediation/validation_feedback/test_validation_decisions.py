"""Correction is bounded independently of publication and traceback path attribution."""

import pytest

from zeroone_ops.models.analysis import (
    ValidationBaseline,
    ValidationCommandResult,
    ValidationResult,
)
from zeroone_ops.models.validation_evidence import SourceChange
from zeroone_ops.services.remediation.validation_feedback.validation_comparison_service import (
    ValidationComparisonService,
)
from zeroone_ops.services.remediation.validation_feedback.validation_feedback_builder import (
    ValidationFeedbackBuilder,
)

COLLECTION = (
    "________________ ERROR collecting tests/test_api.py ________________\n"
    "tests/test_api.py:5: in <module>\n"
    "src/app.py:1: in <module>\n"
    "E   NameError: name 'MissingType' is not defined\n"
    "==================== 2 errors during collection ====================\n"
)


def command_result(command, code=0, output=""):
    return ValidationCommandResult(
        command=command, exit_code=code, stdout=output, stderr="", duration_ms=1
    )


def result(*commands):
    return ValidationResult(
        passed=all(c.exit_code == 0 for c in commands), results=list(commands), summary="validation"
    )


def assess(command, code, output, baseline_code=0, baseline_output="", **kwargs):
    return ValidationComparisonService().assess(
        baseline=ValidationBaseline(
            result=result(command_result(command, baseline_code, baseline_output))
        ),
        post_edit=result(command_result(command, code, output)),
        files_touched=["src/app.py"],
        **kwargs,
    )


@pytest.mark.parametrize(
    "command, code, output, eligible",
    [
        ("uv run pytest", 2, COLLECTION, True),
        (
            "python -m pytest",
            1,
            "FAILED tests/test_api.py::test_title - AssertionError: wrong title",
            True,
        ),
        ("npm test", 1, "tests/api.test.ts: AssertionError: wrong title", True),
        ("cargo test", 1, "test api_test FAILED", True),
        ("pytest", 2, "KeyboardInterrupt", False),
        ("pytest", 2, "ambiguous failure", False),
        ("pytest", 4, "ERROR: unrecognized arguments: --bad", False),
        ("pytest", 5, "no tests ran in 0.01s", False),
        ("npm test", 127, "missing tool", False),
        ("npm test", 124, "timeout", False),
        ("npm test", 126, "permission denied", False),
        ("npm test", -15, "terminated", False),
        ("npm test", 2, "ambiguous exit", False),
        ("npm test", 1, "", False),
        ("env python -m mypy --invalid", 2, "usage: mypy", False),
    ],
)
def test_new_command_failure_can_be_corrected_but_never_published(command, code, output, eligible):
    assessment = assess(command, code, output)
    assert assessment.correction.eligible is eligible
    assert not assessment.comparison.allows_publication
    feedback = ValidationFeedbackBuilder().build(
        assessment=assessment, files_touched=["src/app.py"]
    )
    if eligible:
        assert feedback.allowed_file_paths == ["src/app.py"]
        assert feedback.failures[0].baseline_exit_code == 0
    else:
        assert feedback is None


@pytest.mark.parametrize(
    "command",
    ["pytest", "npm test", "env python -m mypy --bad", "uv run --directory src mypy app.py"],
)
def test_unsupported_baseline_failures_cannot_authorize_edits(command):
    assessment = assess(command, 1, "failed", baseline_code=1, baseline_output="failed")
    assert not assessment.correction.eligible
    assert not assessment.comparison.allows_publication
    assert assessment.problem.phase == "baseline"


def test_operational_failure_overrides_an_eligible_correction_and_selects_actual_blocker():
    baseline = result(command_result("npm test"), command_result("pytest"))
    after = result(
        command_result("npm test", 1, "FAILED title"), command_result("pytest", 127, "missing tool")
    )
    assessment = ValidationComparisonService().assess(
        baseline=ValidationBaseline(result=baseline),
        post_edit=after,
        files_touched=["src/app.py"],
    )
    assert not assessment.correction.eligible
    assert assessment.problem.command_index == 1
    assert not assessment.comparison.allows_publication


def test_preserved_failed_command_does_not_hide_later_blocker():
    mypy = command_result("mypy src", 1, "src/other.py:1: error: Existing issue  [assignment]")
    baseline = result(mypy, command_result("pytest"))
    after = result(mypy, command_result("pytest", 2, COLLECTION))
    assessment = ValidationComparisonService().assess(
        baseline=ValidationBaseline(result=baseline),
        post_edit=after,
        files_touched=["src/app.py"],
    )
    assert assessment.problem.command_index == 1
    assert assessment.correction.eligible
    assert assessment.comparison.baseline_failure_count == 1


def test_absolute_diagnostics_are_mapped_to_the_actual_edited_source():
    diagnostic = "/repo/src/app.py:1: error: Bad value  [assignment]"
    assessment = assess(
        "mypy src --show-absolute-path",
        1,
        diagnostic,
        baseline_code=1,
        baseline_output=diagnostic,
        repository_root="/repo",
        source_changes=(SourceChange("src/app.py", "old\n", "new\n"),),
    )
    assert not assessment.comparison.allows_publication
    assert assessment.correction.eligible
    assert assessment.commands[0].new_diagnostics[0].file_path == "src/app.py"


def test_absolute_and_relative_diagnostics_share_identity_for_proven_relocation():
    assessment = assess(
        "mypy src",
        1,
        "src/app.py:1: error: Bad value  [assignment]",
        baseline_code=1,
        baseline_output="/repo/src/app.py:2: error: Bad value  [assignment]",
        repository_root="/repo",
        source_changes=(SourceChange("src/app.py", "import os\nvalue\n", "value\n"),),
    )
    assert assessment.comparison.outcome == "baseline_preserved"


@pytest.mark.parametrize("path", ["/outside/app.py", "../app.py", "src/../../app.py"])
def test_external_or_escaping_paths_cannot_establish_structured_evidence(path):
    assessment = assess(
        "mypy src", 1, f"{path}:1: error: Bad value  [assignment]", repository_root="/repo"
    )
    assert not assessment.correction.eligible
    assert not assessment.comparison.allows_publication


def test_all_failed_commands_must_be_eligible_and_feedback_is_bounded():
    commands = [f"validator-{index}" for index in range(12)]
    baseline = result(*(command_result(command) for command in commands))
    after = result(*(command_result(command, 1, "failure " + "x" * 500) for command in commands))
    assessment = ValidationComparisonService().assess(
        baseline=ValidationBaseline(result=baseline),
        post_edit=after,
        files_touched=["src/app.py"],
    )
    assert assessment.correction.eligible
    feedback = ValidationFeedbackBuilder().build(
        assessment=assessment, files_touched=["src/app.py"]
    )
    assert 0 < len(feedback.failures) <= 10
    assert feedback.omitted_failure_count == 12 - len(feedback.failures)
    assert sum(len(f.excerpt) + len(f.command) + 150 for f in feedback.failures) < 4_000


def test_feedback_omits_a_whole_failure_instead_of_truncating_its_exception():
    commands = ["validator-" + "a" * 1_000, "validator-" + "b" * 1_000]
    baseline = result(*(command_result(command) for command in commands))
    after = result(
        *(
            command_result(command, 1, "src/app.py:1: in <module>\nNameError: " + "x" * 1_700)
            for command in commands
        )
    )
    assessment = ValidationComparisonService().assess(
        baseline=ValidationBaseline(result=baseline),
        post_edit=after,
        files_touched=["src/app.py"],
    )
    feedback = ValidationFeedbackBuilder().build(
        assessment=assessment, files_touched=["src/app.py"]
    )
    assert len(feedback.failures) == 1
    assert feedback.omitted_failure_count == 1
    assert "NameError: " + "x" * 1_700 in feedback.failures[0].excerpt


@pytest.mark.parametrize("command", ["mypy src", "ruff check src"])
def test_unsupported_format_after_clean_baseline_can_only_authorize_correction(command):
    output = "A new diagnostic format that this parser does not support"
    assessment = assess(command, 1, output)
    assert assessment.commands[0].health == "validation_failure"
    assert assessment.correction.eligible
    assert not assessment.comparison.allows_publication
    feedback = ValidationFeedbackBuilder().build(
        assessment=assessment, files_touched=["src/app.py"]
    )
    assert output in feedback.failures[0].excerpt
    assert feedback.allowed_file_paths == ["src/app.py"]

    failed_baseline = assess(command, 1, output, baseline_code=1, baseline_output=output)
    assert not failed_baseline.correction.eligible
    assert not failed_baseline.comparison.allows_publication
    assert failed_baseline.problem.phase == "baseline"


@pytest.mark.parametrize(
    "command, output",
    [
        ("ruff check src", "All checks passed!"),
        ("mypy src", "Success: no issues found in 1 source file"),
        ("mypy src", "src/app.py:0: error: Bad location  [assignment]"),
    ],
)
def test_contradictory_evidence_still_withholds_correction_after_clean_baseline(command, output):
    assessment = assess(command, 1, output)
    assert not assessment.correction.eligible
    assert not assessment.comparison.allows_publication
