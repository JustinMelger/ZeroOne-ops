"""Capture validation evidence before a remediation patch is applied."""

from __future__ import annotations

from zeroone_ops.models.analysis import ValidationBaseline
from zeroone_ops.services.remediation.validator import Validator


class ValidationBaselineService:
    """Capture one complete validation baseline for a remediation attempt."""

    def __init__(self, validator: Validator) -> None:
        """Initialize the service with the shared validator."""
        self.validator = validator

    def capture(self, commands: list[str]) -> ValidationBaseline:
        """Run every configured command and return its ordered baseline result."""
        return ValidationBaseline(result=self.validator.run_all(commands))
