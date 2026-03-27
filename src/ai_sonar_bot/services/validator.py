"""Validation service.

This module executes configured project validation commands in sequence.
"""

from __future__ import annotations

import subprocess
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
        results: list[ValidationCommandResult] = []
        for command in commands:
            started = time.perf_counter()
            completed = subprocess.run(
                command,
                cwd=self.repo_root,
                shell=True,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            results.append(
                ValidationCommandResult(
                    command=command,
                    exit_code=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                    duration_ms=duration_ms,
                )
            )
            if completed.returncode != 0:
                return ValidationResult(
                    passed=False,
                    results=results,
                    summary=f"Validation failed: {command}",
                )
        return ValidationResult(
            passed=True,
            results=results,
            summary="All validation commands passed.",
        )
