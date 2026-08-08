"""Parse deterministic GitHub work-item issue bodies."""

from __future__ import annotations

import json
import re

from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.github_client import GitHubClientError

_WORK_ITEM_STATE_BLOCK_PATTERN = re.compile(
    (
        r"<details>\n"
        r"<summary><code>zeroone-work-item-state</code> machine state</summary>\n\n"
        r"```json\n(?P<payload>.*?)\n```\n\n"
        r"</details>"
    ),
    re.DOTALL,
)
_MACHINE_STATE_SECTION = "## Machine State\n\n"


class GitHubWorkItemParser:
    """Parse deterministic GitHub work-item issue bodies."""

    def parse_work_item_state(self, body: str) -> WorkItemState | None:
        """Return the canonical work-item state when present."""
        matches = list(_WORK_ITEM_STATE_BLOCK_PATTERN.finditer(body))
        if not matches:
            return None
        match = matches[0]
        if (
            len(matches) != 1
            or not body[: match.start()].endswith(_MACHINE_STATE_SECTION)
            or body[match.end() :].strip()
        ):
            raise GitHubClientError(
                "GitHub work-item state block was not the final renderer-owned block."
            )
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as error:
            raise GitHubClientError(
                "GitHub work-item state block contained invalid JSON."
            ) from error
        return WorkItemState.model_validate(payload)
