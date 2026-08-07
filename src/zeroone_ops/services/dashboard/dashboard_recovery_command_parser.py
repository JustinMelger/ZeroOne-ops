"""Parse strict GitLab dashboard-note remediation recovery commands."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import cast

from zeroone_ops.models.work_item import RecoveryAction

_RECOVERY_COMMAND_PATTERN = re.compile(
    r"^\s*/zeroone\s+remediation\s+(?P<item_id>\S+)\s+(?P<action>dismiss|retry)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DashboardRecoveryCommandParseResult:
    """Represent one parsed dashboard recovery command."""

    matched_prefix: bool
    item_id: str | None = None
    action: RecoveryAction | None = None


class DashboardRecoveryCommandParser:
    """Parse recovery commands that identify one dashboard item explicitly."""

    def parse(self, body: str | None) -> DashboardRecoveryCommandParseResult:
        """Return one strict recovery command parse result."""
        if body is None or not body.lstrip().lower().startswith("/zeroone remediation"):
            return DashboardRecoveryCommandParseResult(matched_prefix=False)
        match = _RECOVERY_COMMAND_PATTERN.match(body)
        if match is None:
            return DashboardRecoveryCommandParseResult(matched_prefix=True)
        return DashboardRecoveryCommandParseResult(
            matched_prefix=True,
            item_id=match.group("item_id"),
            action=cast(RecoveryAction, match.group("action").lower()),
        )
