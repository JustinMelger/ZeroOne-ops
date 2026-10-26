"""Separate command execution health from publication and correction decisions."""

import re
from typing import Literal

from zeroone_ops.models.analysis import ValidationCommandResult
from zeroone_ops.services.remediation.validation_feedback.diagnostic_parser import (
    execution_failure,
    validation_executable,
)


def command_health(
    result: ValidationCommandResult,
) -> Literal["passed", "validation_failure", "execution_failure", "unclassified"]:
    """A normal failure may justify correction but never authorizes publication."""
    if execution_failure(result):
        return "execution_failure"
    if result.exit_code == 0:
        return "passed"
    output = f"{result.stdout}\n{result.stderr}"
    if not output.strip():
        return "unclassified"
    if result.exit_code == 1:
        return "validation_failure"
    if validation_executable(result.command) in {"pytest", "py.test"} and result.exit_code == 2:
        collection = re.search(r"(?m)^.*ERROR collecting\s+\S+", output)
        exception = re.search(r"(?m)^\s*(?:E\s+)?[\w.]*(?:Error|Exception):\s*\S", output)
        if collection and exception and "KeyboardInterrupt" not in output:
            return "validation_failure"
    return "unclassified"
