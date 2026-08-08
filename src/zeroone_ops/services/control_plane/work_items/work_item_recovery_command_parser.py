"""Parse provider-neutral work-item recovery commands without interpreting state."""

from __future__ import annotations

import re
from dataclasses import dataclass

from zeroone_ops.models.work_item import RecoveryAction

_RECOVERY_PREFIX = re.compile(r"^\s*/zeroone\s+remediation\b", re.IGNORECASE)
_RECOVERY_COMMAND = re.compile(
    r"^\s*/zeroone\s+remediation\s+(dismiss|requeue)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WorkItemRecoveryCommand:
    """Describe whether one comment contains a supported recovery command."""

    matched_prefix: bool
    action: RecoveryAction | None = None


class WorkItemRecoveryCommandParser:
    """Parse only standalone work-item recovery commands."""

    def parse(self, body: str | None) -> WorkItemRecoveryCommand:
        """Return one parsed command or a prefix-only invalid command result."""
        if body is None or not _RECOVERY_PREFIX.match(body):
            return WorkItemRecoveryCommand(matched_prefix=False)
        match = _RECOVERY_COMMAND.match(body)
        if match is None:
            return WorkItemRecoveryCommand(matched_prefix=True)
        return WorkItemRecoveryCommand(
            matched_prefix=True,
            action=match.group(1).lower(),  # type: ignore[arg-type]
        )
