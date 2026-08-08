"""Parse the GitHub policy issue body."""

from __future__ import annotations

import json
import re

from zeroone_ops.models.dashboard import DashboardPolicyState
from zeroone_ops.providers.github_client import GitHubClientError

_POLICY_STATE_BLOCK_PATTERN = re.compile(
    (
        r"<details>\n"
        r"<summary><code>zeroone-policy-state</code> machine state</summary>\n\n"
        r"```json\n(?P<payload>.*?)\n```\n\n"
        r"</details>"
    ),
    re.DOTALL,
)
_MACHINE_STATE_SECTION = "## Machine State\n\n"


class GitHubPolicyIssueParser:
    """Parse deterministic GitHub policy issue bodies."""

    def parse_policy_state(self, body: str) -> DashboardPolicyState:
        """Return the canonical policy state when present."""
        matches = list(_POLICY_STATE_BLOCK_PATTERN.finditer(body))
        if not matches:
            return DashboardPolicyState()
        match = matches[0]
        if (
            len(matches) != 1
            or not body[: match.start()].endswith(_MACHINE_STATE_SECTION)
            or body[match.end() :].strip()
        ):
            raise GitHubClientError(
                "GitHub policy state block was not the final renderer-owned block."
            )
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as error:
            raise GitHubClientError("GitHub policy state block contained invalid JSON.") from error
        return DashboardPolicyState.model_validate(payload)
