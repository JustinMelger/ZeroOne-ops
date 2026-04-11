"""Validation service.

This module executes configured project validation commands in sequence.
"""

from __future__ import annotations

# Bandit: this service intentionally uses subprocess for configured validation commands.
import subprocess  # nosec B404
import time
from pathlib import Path

from ai_sonar_bot.models.analysis import ValidationCommandResult, ValidationResult


class Validator:
    """Run configured validation commands sequentially.

    Args:
        repo_root: Repository root directory.
        timeout_seconds: Per-command timeout in seconds.
    """

    def __init__(self, repo_root: Path, timeout_seconds: int = 600) -> None:
        """Initialize the validator.

        Args:
            repo_root: Repository root directory.
            timeout_seconds: Per-command timeout in seconds.
        """
        self.repo_root = repo_root
        self.timeout_seconds = timeout_seconds

    def run(self, commands: list[str]) -> ValidationResult:
        """Run validation commands.

        Args:
            commands: Shell commands to execute in order.

        Returns:
            Structured validation results for the executed commands.
        """
        if not commands:
            return ValidationResult(
                passed=True,
                results=[],
                summary="No validation commands configured.",
            )
        results: list[ValidationCommandResult] = []
        for command in commands:
            result = self._run_command(command)
            results.append(result)
            if result.exit_code != 0:
                return ValidationResult(
                    passed=False,
                    results=results,
                    summary=(f"Validation failed: {command} (exit code {result.exit_code})."),
                )
        return ValidationResult(
            passed=True,
            results=results,
            summary="All validation commands passed.",
        )

    def _run_command(self, command: str) -> ValidationCommandResult:
        """Run a single validation command.

        Args:
            command: Shell command to execute.

        Returns:
            Structured result for the executed command.
        """
        started = time.perf_counter()
        try:
            # Validation commands are repository-controlled configuration
            # and may rely on shell syntax.
            completed = subprocess.run(  # nosec B603
                ["/bin/sh", "-lc", command],
                cwd=self.repo_root,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            returncode = 124
            stdout = _coerce_output(error.stdout)
            stderr = _coerce_output(error.stderr)
            stderr = f"{stderr}\nCommand timed out after {self.timeout_seconds}s.".strip()
        duration_ms = int((time.perf_counter() - started) * 1000)
        return ValidationCommandResult(
            command=command,
            exit_code=returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )


def _coerce_output(value: bytes | str | None) -> str:
    """Normalize subprocess output values to strings.

    Args:
        value: Captured subprocess output value.

    Returns:
        Decoded string output.
    """
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
