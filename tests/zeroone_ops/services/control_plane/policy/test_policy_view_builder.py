from pathlib import Path

import pytest

from zeroone_ops.models.policy import (
    PolicyIssueClassStateEntry,
    PolicySeverityStateEntry,
    PolicyState,
)
from zeroone_ops.services.control_plane.policy.github_policy_issue_parser import (
    GitHubPolicyIssueParser,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_parser import (
    GitLabPolicyIssueParser,
)
from zeroone_ops.services.control_plane.policy.policy_issue_renderer import PolicyIssueRenderer
from zeroone_ops.services.control_plane.policy.policy_view_builder import PolicyViewBuilder


@pytest.mark.parametrize("configured,enabled", [([], ["low", "medium"]), (["HIGH"], ["high"])])
def test_policy_bootstrap_preserves_exclusions_and_input(
    tmp_path: Path, configured: list[str], enabled: list[str]
) -> None:
    builder = PolicyViewBuilder(bootstrap_severities=configured)
    state = PolicyState(
        issue_class_exclusions=[
            PolicyIssueClassStateEntry(source="ruff", issue_key="E1", reason="operator")
        ]
    )
    before = state.model_dump()
    resolved = builder.resolve_policy_state(state)
    assert state.model_dump() == before
    assert [row.severity for row in resolved.severity_policy] == ["low", "medium", "high"]
    assert [row.severity for row in resolved.severity_policy if row.enabled] == enabled
    assert all(row.updated_by == "config_seed" for row in resolved.severity_policy)
    assert all(
        row.reason == (None if row.enabled else "Disabled by current config baseline.")
        for row in resolved.severity_policy
    )
    assert resolved.issue_class_exclusions == state.issue_class_exclusions
    resolved.issue_class_exclusions[0].reason = "changed"
    assert state.model_dump() == before


def test_partial_policy_and_exact_issue_rendering(tmp_path: Path) -> None:
    builder = PolicyViewBuilder(bootstrap_severities=["low", "medium"])
    state = PolicyState(
        severity_policy=[PolicySeverityStateEntry(severity="high", enabled=True, reason="chosen")],
        issue_class_exclusions=[
            PolicyIssueClassStateEntry(source="ruff", issue_key="E1", reason="operator")
        ],
    )
    resolved = builder.resolve_policy_state(state)
    assert resolved == state and resolved is not state
    view = builder.build(policy_state=resolved)
    assert [(row.severity, row.enabled, row.reason) for row in view.severity_policy] == [
        ("low", False, None),
        ("medium", False, None),
        ("high", True, "chosen"),
    ]
    assert view.excluded_issue_classes[0].matching_items_count == 0
    body = PolicyIssueRenderer().render(policy_state=resolved, policy_view=view)
    assert body == (Path(__file__).parent / "fixtures" / "policy_body.txt").read_text()
    assert GitHubPolicyIssueParser().parse_policy_state(body) == state
    assert GitLabPolicyIssueParser().parse_policy_state(body) == state


def test_neutral_builder_copies_seed_and_keeps_exclusion_order() -> None:
    seed = ["high"]
    builder = PolicyViewBuilder(bootstrap_severities=seed)
    seed.clear()
    state = builder.resolve_policy_state(None)
    assert [row.severity for row in state.severity_policy if row.enabled] == ["high"]
    state.issue_class_exclusions = [
        PolicyIssueClassStateEntry(source="z", issue_key="2", reason="second"),
        PolicyIssueClassStateEntry(source="a", issue_key="1", reason="first"),
    ]
    before = state.model_dump()
    view = builder.build(policy_state=state)
    assert [row.source for row in view.excluded_issue_classes] == ["z", "a"]
    view.excluded_issue_classes[0].reason = "changed"
    view.severity_policy[0].enabled = True
    assert state.model_dump() == before
