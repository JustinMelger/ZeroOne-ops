"""Tests for remediation workflow routing and summary behavior."""

from pathlib import Path

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
            "gitlab": {"target_branch": "main", "control_plane_mode": "issues"},
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
        is_gitlab_issue_mode=_is_gitlab_issue_mode,
        load_github_config=lambda: GitHubConnectionConfig(
            api_url="https://api.github.example.com",
            server_url="https://github.example.com",
            token="token",
            repository="octo-org/octo-repo",
        ),
        load_gitlab_config=unexpected_gitlab_load,
        build_dashboard_policy_view=unexpected_summary,  # type: ignore[arg-type]
        publish_github_summary=unexpected_summary,  # type: ignore[arg-type]
        publish_gitlab_summary=unexpected_summary,  # type: ignore[arg-type]
    )

    summary = workflow.run()

    assert summary.status == RunStatus.NO_ISSUE


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
        is_gitlab_issue_mode=_is_gitlab_issue_mode,
        load_github_config=unexpected_github_load,
        load_gitlab_config=lambda: GitLabConnectionConfig(
            url="https://gitlab.example.com",
            token="token",
            project_id="group/project",
        ),
        build_dashboard_policy_view=unexpected_summary,  # type: ignore[arg-type]
        publish_github_summary=unexpected_summary,  # type: ignore[arg-type]
        publish_gitlab_summary=unexpected_summary,  # type: ignore[arg-type]
    )

    summary = workflow.run()

    assert summary.status == RunStatus.FAILED
