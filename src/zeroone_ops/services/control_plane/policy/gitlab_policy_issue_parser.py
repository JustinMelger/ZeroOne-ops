"""Parse the GitLab policy issue body."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from zeroone_ops.models.dashboard import DashboardPolicyState
from zeroone_ops.providers.gitlab_client import GitLabClientError

_POLICY_STATE_BLOCK_PATTERN = re.compile(
    (
        r"<details>\n"
        r"<summary><code>zeroone-policy-state</code> machine state</summary>\n\n"
        r"```json\n(?P<payload>.*?)\n```\n\n"
        r"</details>"
    ),
    re.DOTALL,
)


class GitLabPolicyIssueParser:
    """Parse deterministic GitLab policy issue bodies."""

    def parse_policy_state(self, body: str) -> DashboardPolicyState:
        """Return canonical policy state, or an empty state when absent."""
        match = _POLICY_STATE_BLOCK_PATTERN.search(body)
        if match is None:
            return DashboardPolicyState()
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as error:
            raise GitLabClientError("GitLab policy state block contained invalid JSON.") from error
        try:
            return DashboardPolicyState.model_validate(payload)
        except ValidationError as error:
            raise GitLabClientError("GitLab policy state block was invalid.") from error
