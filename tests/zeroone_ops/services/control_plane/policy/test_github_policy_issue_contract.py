import pytest

from zeroone_ops.models.policy import PolicyState, PolicyView
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.services.control_plane.policy.github_policy_issue_parser import (
    GitHubPolicyIssueParser,
)
from zeroone_ops.services.control_plane.policy.policy_issue_renderer import (
    PolicyIssueRenderer,
)


@pytest.mark.parametrize(
    "suffix",
    [
        "\n<details>\n<summary><code>zeroone-policy-state</code> machine state</summary>\n\n"
        "```json\n{}\n```\n\n</details>\n",
        "\nUnexpected trailing text.\n",
    ],
)
def test_parser_rejects_nonfinal_or_duplicate_machine_policy_state(suffix: str) -> None:
    body = PolicyIssueRenderer().render(
        policy_state=PolicyState(),
        policy_view=PolicyView(),
    )

    with pytest.raises(GitHubClientError, match="final renderer-owned block"):
        GitHubPolicyIssueParser().parse_policy_state(body + suffix)
