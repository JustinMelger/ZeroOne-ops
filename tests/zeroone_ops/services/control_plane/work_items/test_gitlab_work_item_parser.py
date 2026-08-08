import pytest

from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_parser import (
    GitLabWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_renderer import (
    GitLabWorkItemRenderer,
)

from .test_support import build_work_item


def test_parse_work_item_state_round_trips_rendered_body() -> None:
    body = GitLabWorkItemRenderer().render_body(build_work_item())

    parsed = GitLabWorkItemParser().parse_work_item_state(body)

    assert parsed is not None
    assert parsed.identity_key == build_work_item().identity_key


def test_parse_work_item_state_rejects_invalid_machine_payload() -> None:
    body = """## Machine State

<details>
<summary><code>zeroone-work-item-state</code> machine state</summary>

```json
{"status": "unsupported"}
```

</details>
"""

    with pytest.raises(GitLabClientError, match="state block was invalid"):
        GitLabWorkItemParser().parse_work_item_state(body)


def test_parse_work_item_state_rejects_embedded_state_block() -> None:
    body = GitLabWorkItemRenderer().render_body(build_work_item())
    state_block = body.split("## Machine State\n\n", maxsplit=1)[1]
    body = body.replace("## Status", f"{state_block}\n## Status", 1)

    with pytest.raises(GitLabClientError, match="final renderer-owned block"):
        GitLabWorkItemParser().parse_work_item_state(body)


def test_parse_work_item_state_rejects_content_after_machine_state() -> None:
    body = GitLabWorkItemRenderer().render_body(build_work_item()) + "\nOperator note\n"

    with pytest.raises(GitLabClientError, match="final renderer-owned block"):
        GitLabWorkItemParser().parse_work_item_state(body)
