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
    body = """<details>
<summary><code>zeroone-work-item-state</code> machine state</summary>

```json
{"status": "unsupported"}
```

</details>
"""

    with pytest.raises(GitLabClientError, match="state block was invalid"):
        GitLabWorkItemParser().parse_work_item_state(body)
