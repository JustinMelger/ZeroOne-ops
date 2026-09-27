from pathlib import Path

import pytest

from zeroone_ops.models.config import AppConfig, GitLabConfig, RemediationConfig
from zeroone_ops.models.state import AppState, RepositoryState
from zeroone_ops.services.control_plane.policy.policy_view_builder import PolicyViewBuilder
from zeroone_ops.services.workflows import provider_workflow_builders as builders


@pytest.mark.parametrize("provider", ["github", "gitlab"])
def test_issue_policy_uses_only_neutral_builder_and_selected_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    calls: list[str] = []

    def unexpected(*args: object, **kwargs: object) -> None:
        raise AssertionError("Issue policy must not construct dashboard dependencies")

    def credentials() -> object:
        calls.append(provider)
        return object()

    monkeypatch.setattr(builders, "DashboardPolicyViewBuilder", unexpected)
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_policy_view_builder.DashboardItemSelector",
        unexpected,
    )
    for name in ("github", "gitlab"):
        monkeypatch.setattr(
            builders,
            f"load_{name}_connection_config",
            credentials if name == provider else unexpected,
        )
    monkeypatch.setattr(builders, "GitHubPolicyClient", lambda config: object())
    monkeypatch.setattr(builders, "GitLabPolicyClient", lambda config: object())
    config = AppConfig(
        base_branch="main",
        gitlab=GitLabConfig(target_branch="main"),
        remediation=RemediationConfig(target_branch="main", bootstrap_severities=["high"]),
    )
    service = getattr(builders, f"build_{provider}_policy_issue_service")(
        repo_root=tmp_path / "nonexistent",
        config=config,
        state=AppState(repository=RepositoryState(base_branch="main")),
    )
    assert type(service.policy_view_builder) is PolicyViewBuilder
    policy = service.policy_view_builder.resolve_policy_state(None)
    assert [row.severity for row in policy.severity_policy if row.enabled] == ["high"]
    assert calls == [provider]
