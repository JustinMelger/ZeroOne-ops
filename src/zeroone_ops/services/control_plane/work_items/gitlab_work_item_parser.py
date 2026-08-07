"""Parse deterministic GitLab work-item issue bodies."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.providers.gitlab_client import GitLabClientError

_WORK_ITEM_STATE_BLOCK_PATTERN = re.compile(
    (
        r"<details>\n"
        r"<summary><code>zeroone-work-item-state</code> machine state</summary>\n\n"
        r"```json\n(?P<payload>.*?)\n```\n\n"
        r"</details>"
    ),
    re.DOTALL,
)


class GitLabWorkItemParser:
    """Parse deterministic GitLab work-item issue bodies."""

    def parse_work_item_state(self, body: str) -> WorkItemState | None:
        """Return the canonical work-item state when present."""
        match = _WORK_ITEM_STATE_BLOCK_PATTERN.search(body)
        if match is None:
            return None
        try:
            payload = json.loads(match.group("payload"))
        except json.JSONDecodeError as error:
            raise GitLabClientError(
                "GitLab work-item state block contained invalid JSON."
            ) from error
        try:
            return WorkItemState.model_validate(payload)
        except ValidationError as error:
            raise GitLabClientError("GitLab work-item state block was invalid.") from error
