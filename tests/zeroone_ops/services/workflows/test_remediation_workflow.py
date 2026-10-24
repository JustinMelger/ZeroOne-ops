"""Tests for remediation workflow routing and summary behavior."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from zeroone_ops.models.config import AppConfig, GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.workflows.remediation_workflow import RemediationWorkflow
from zeroone_ops.services.workflows.workflow_run_context import build_workflow_run_context


def _github_config(*, state_path: Path) -> AppConfig:
    """Build minimal GitHub remediation configuration."""
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
    """Build minimal GitLab issue-mode remediation configuration."""
    return AppConfig.model_validate(
        {
            "platform": "gitlab",
            "base_branch": "main",
            "remediation": {"target_branch": "main"},
            "gitlab": {"control_plane_mode": "issues"},
            "state": {"path": state_path},
        }
    )


def _is_gitlab_issue_mode(config: AppConfig) -> bool:
    """Return whether the test configuration selects GitLab issue mode."""
    return (
        config.platform == "gitlab"
        and config.require_gitlab_config(reason="test").control_plane_mode == "issues"
    )


def test_github_no_issue_does_not_load_gitlab_or_publish_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """GitHub remediation loads only GitHub and skips a no-issue summary refresh."""
    monkeypatch.chdir(tmp_path)

    class StubGitHubRemediationRunner:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def run(self, **kwargs: object) -> RunSummary:
            del kwargs
            return RunSummary(
                run_id="run-1",
                status=RunStatus.NO_ISSUE,
                message="[ci] No eligible GitHub work items.",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    monkeypatch.setattr(
        "zeroone_ops.services.workflows.remediation_workflow.GitHubRemediationRunner",
        StubGitHubRemediationRunner,
    )

    def unexpected_gitlab_load() -> GitLabConnectionConfig:
        raise AssertionError("GitLab configuration should stay lazy for GitHub remediation.")

    def unexpected_summary(**kwargs: object) -> object:
        del kwargs
        raise AssertionError("No-issue remediation must not publish an operational summary.")

    workflow = RemediationWorkflow(
        config=_github_config(state_path=tmp_path / ".zeroone-ops-state.json"),
        dry_run=False,
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
        publish_github_summary=unexpected_summary,  # type: ignore[arg-type]
        publish_gitlab_summary=unexpected_summary,  # type: ignore[arg-type]
    )

    summary = workflow.run()

    assert summary.status == RunStatus.NO_ISSUE


def test_github_dry_run_does_not_create_workflow_trace(tmp_path: Path, monkeypatch) -> None:
    """Dry-run remediation does not create an MLflow root trace."""
    monkeypatch.chdir(tmp_path)

    class StubGitHubRemediationRunner:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def run(self, **kwargs: object) -> RunSummary:
            assert kwargs["active_dry_run"] is True
            return RunSummary(
                run_id="run-1",
                status=RunStatus.NO_ISSUE,
                message="[ci] No eligible GitHub work items.",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    monkeypatch.setattr(
        "zeroone_ops.services.workflows.remediation_workflow.GitHubRemediationRunner",
        StubGitHubRemediationRunner,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.workflows.remediation_workflow.WorkflowTraceService.trace",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Dry-run remediation must not create an MLflow root trace.")
        ),
    )

    workflow = RemediationWorkflow(
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
        load_gitlab_config=lambda: (_ for _ in ()).throw(AssertionError("Unexpected GitLab load.")),
        publish_github_summary=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Dry-run remediation must not publish a summary.")
        ),
        publish_gitlab_summary=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Unexpected GitLab summary publication.")
        ),
    )

    assert workflow.run().status is RunStatus.NO_ISSUE


def test_gitlab_issue_mode_can_suppress_summary_for_combined_control_plane(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Combined GitLab control-plane runs publish their summary only once at the end."""
    monkeypatch.chdir(tmp_path)

    class StubGitLabRemediationRunner:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def run(self, **kwargs: object) -> RunSummary:
            del kwargs
            return RunSummary(
                run_id="run-1",
                status=RunStatus.FAILED,
                message="[ci] Validation failed.",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    monkeypatch.setattr(
        "zeroone_ops.services.workflows.remediation_workflow.GitLabRemediationRunner",
        StubGitLabRemediationRunner,
    )

    def unexpected_github_load() -> GitHubConnectionConfig:
        raise AssertionError("GitHub configuration should stay lazy for GitLab remediation.")

    def unexpected_summary(**kwargs: object) -> object:
        del kwargs
        raise AssertionError("The combined control-plane workflow suppresses this publication.")

    workflow = RemediationWorkflow(
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
        publish_github_summary=unexpected_summary,  # type: ignore[arg-type]
        publish_gitlab_summary=unexpected_summary,  # type: ignore[arg-type]
    )

    summary = workflow.run()

    assert summary.status == RunStatus.FAILED


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_batch_policy_loader_is_read_only_and_lazy(tmp_path, monkeypatch, platform):
    monkeypatch.chdir(tmp_path)
    policy_service = Mock()
    builder = Mock(return_value=policy_service)
    prefix = "zeroone_ops.services.workflows.remediation_workflow."
    monkeypatch.setattr(prefix + f"build_{platform}_policy_issue_service", builder)

    class SelectingRunner:
        def __init__(self, *, load_batch_policy, **kwargs):
            builder.assert_not_called()
            self.load_policy = load_batch_policy

        def run(self, **kwargs):
            assert self.load_policy() is policy_service.load_policy_state.return_value
            return RunSummary(
                run_id="run-1",
                status=RunStatus.NO_ISSUE,
                message="No work",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    monkeypatch.setattr(
        prefix + ("GitHub" if platform == "github" else "GitLab") + "RemediationRunner",
        SelectingRunner,
    )
    config = (_github_config if platform == "github" else _gitlab_issue_config)(
        state_path=tmp_path / ".zeroone-ops-state.json"
    )
    workflow = RemediationWorkflow(
        config=config,
        dry_run=True,
        publish_operational_summary=False,
        build_run_id=lambda: "run-1",
        build_context=build_workflow_run_context,
        load_github_config=lambda: GitHubConnectionConfig(
            token="token",
            repository="team/repo",
            api_url="https://api.github.example",
            server_url="https://github.example",
        ),
        load_gitlab_config=lambda: GitLabConnectionConfig(
            url="https://gitlab.example", token="token", project_id="team/repo"
        ),
        publish_github_summary=Mock(),
        publish_gitlab_summary=Mock(),
    )
    assert workflow.run().status == RunStatus.NO_ISSUE
    builder.assert_called_once()
    policy_service.load_policy_state.assert_called_once_with(
        **{"repository_id" if platform == "github" else "project_id": "team/repo"},
        persist=False,
    )
