from pathlib import Path

from zeroone_ops.services.remediation.validator import Validator


def test_run_returns_success_when_no_commands_configured(tmp_path: Path) -> None:
    result = Validator(tmp_path).run([])

    assert result.passed is True
    assert result.results == []
    assert result.summary == "No validation commands configured."


def test_run_captures_successful_command_output(tmp_path: Path) -> None:
    result = Validator(tmp_path).run(["printf 'ok'"])

    assert result.passed is True
    assert len(result.results) == 1
    assert result.results[0].stdout == "ok"
    assert result.summary == "All validation commands passed."


def test_run_stops_after_first_failed_command(tmp_path: Path) -> None:
    result = Validator(tmp_path).run(["false", "printf 'never'"])

    assert result.passed is False
    assert len(result.results) == 1
    assert result.results[0].exit_code != 0
    assert "exit code" in result.summary


def test_run_surfaces_clear_message_for_command_not_found(tmp_path: Path) -> None:
    result = Validator(tmp_path).run(["missing-validation-tool --version"])

    assert result.passed is False
    assert len(result.results) == 1
    assert result.results[0].exit_code == 127
    assert "Validation could not run" in result.summary
    assert "not available in the current environment" in result.summary


def test_run_surfaces_clear_message_for_non_executable_command(tmp_path: Path) -> None:
    script = tmp_path / "not_executable.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    result = Validator(tmp_path).run([f"./{script.name}"])

    assert result.passed is False
    assert len(result.results) == 1
    assert result.results[0].exit_code == 126
    assert "Validation could not run" in result.summary
    assert "not executable in the current environment" in result.summary
