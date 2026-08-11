"""Tests for policy workflow routing and summary behavior."""

from pathlib import Path

from zeroone_ops.models.config import AppConfig, GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.workflows.policy_workflow import PolicyWorkflow
from zeroone_ops.services.workflows.workflow_run_context import build_workflow_run_context


def _github_config(*, state_path: Path) -> AppConfig:
    """Build minimal GitHub policy configuration."""
    return AppConfig.model_validate(
        {
            "platform": "github",
            "base_branch": "main",
            "remediation": {"target_branch": "main"},
            "github": {"labels": []},
            "state": {"path": state_path},
        }
    )


def _gitlab_issue_config(*, state_path: Path) -> AppConfig:
    """Build minimal GitLab issue-mode policy configuration."""
    return AppConfig.model_validate(
        {
            "platform": "gitlab",
            "base_branch": "main",
            "remediation": {"target_branch": "main"},
            "gitlab": {"target_branch": "main", "control_plane_mode": "issues"},
            "state": {"path": state_path},
        }
    )


def test_github_policy_loads_only_github_provider_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """GitHub policy processing does not load GitLab dependencies."""
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    class StubPolicyRunner:
        def run(self, **kwargs: object) -> RunSummary:
            captured.update(kwargs)
            return RunSummary(
                run_id="run-1",
                status=RunStatus.SYNCED,
                message="[ci] Policy processed.",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    def unexpected_gitlab_load() -> GitLabConnectionConfig:
        raise AssertionError("GitLab configuration should stay lazy for GitHub policy.")

    def unexpected_dependency(**kwargs: object) -> object:
        del kwargs
        raise AssertionError("Only the GitHub policy runner should be built.")

    workflow = PolicyWorkflow(
        config=_github_config(state_path=tmp_path / ".zeroone-ops-state.json"),
        dry_run=True,
        publish_operational_summary=True,
        build_run_id=lambda: "run-1",
        build_context=build_workflow_run_context,
        load_github_config=lambda: GitHubConnectionConfig(
            api_url="https://api.github.example.com",
            server_url="https://github.example.com",
            token="token",
            repository="octo-org/octo-repo",
        ),
        load_gitlab_config=unexpected_gitlab_load,
        build_dashboard_policy_view=unexpected_dependency,  # type: ignore[arg-type]
        build_github_policy_runner=lambda **kwargs: StubPolicyRunner(),  # type: ignore[arg-type]
        build_gitlab_policy_runner=unexpected_dependency,  # type: ignore[arg-type]
        publish_gitlab_summary=unexpected_dependency,  # type: ignore[arg-type]
    )

    summary = workflow.run()

    assert summary.status is RunStatus.SYNCED
    assert captured["repository_id"] == "octo-org/octo-repo"
    assert captured["active_dry_run"] is True


def test_gitlab_issue_policy_can_suppress_summary_for_combined_control_plane(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Combined GitLab control-plane runs defer policy summary publication."""
    monkeypatch.chdir(tmp_path)

    class StubPolicyRunner:
        def run(self, **kwargs: object) -> RunSummary:
            del kwargs
            return RunSummary(
                run_id="run-1",
                status=RunStatus.SYNCED,
                message="[ci] Policy processed.",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    def unexpected_github_load() -> GitHubConnectionConfig:
        raise AssertionError("GitHub configuration should stay lazy for GitLab policy.")

    def unexpected_dependency(**kwargs: object) -> object:
        del kwargs
        raise AssertionError("Combined control-plane policy must not publish an overview here.")

    workflow = PolicyWorkflow(
        config=_gitlab_issue_config(state_path=tmp_path / ".zeroone-ops-state.json"),
        dry_run=False,
        publish_operational_summary=False,
        build_run_id=lambda: "run-1",
        build_context=build_workflow_run_context,
        load_github_config=unexpected_github_load,
        load_gitlab_config=lambda: GitLabConnectionConfig(
            url="https://gitlab.example.com",
            token="token",
            project_id="group/project",
        ),
        build_dashboard_policy_view=unexpected_dependency,  # type: ignore[arg-type]
        build_github_policy_runner=unexpected_dependency,  # type: ignore[arg-type]
        build_gitlab_policy_runner=lambda **kwargs: StubPolicyRunner(),  # type: ignore[arg-type]
        publish_gitlab_summary=unexpected_dependency,  # type: ignore[arg-type]
    )

    summary = workflow.run()

    assert summary.status is RunStatus.SYNCED
