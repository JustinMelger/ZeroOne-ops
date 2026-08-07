import pytest

from zeroone_ops.models.dashboard import DashboardPolicyState, DashboardPolicyView
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_parser import (
    GitLabPolicyIssueParser,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_renderer import (
    GitLabPolicyIssueRenderer,
)


def test_policy_state_round_trips_the_gitlab_policy_issue_body() -> None:
    state = DashboardPolicyState()
    body = GitLabPolicyIssueRenderer().render(
        policy_state=state,
        policy_view=DashboardPolicyView(),
    )

    assert GitLabPolicyIssueParser().parse_policy_state(body) == state
    assert "/zeroone policy severity enable high" in body


def test_parser_rejects_invalid_machine_policy_state() -> None:
    body = """<details>
<summary><code>zeroone-policy-state</code> machine state</summary>

```json
{"severity_policy": "invalid"}
```

</details>
"""

    with pytest.raises(GitLabClientError, match="state block was invalid"):
        GitLabPolicyIssueParser().parse_policy_state(body)
