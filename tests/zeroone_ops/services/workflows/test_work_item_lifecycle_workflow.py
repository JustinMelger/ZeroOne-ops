"""Tests for work-item lifecycle workflow routing and lazy provider setup."""

from pathlib import Path

from zeroone_ops.models.config import AppConfig, GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.workflows.work_item_lifecycle_workflow import (
    WorkItemLifecycleWorkflow,
)
from zeroone_ops.services.workflows.workflow_run_context import build_workflow_run_context


def test_github_local_lifecycle_fails_before_loading_provider_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Live lifecycle execution remains CI-only without triggering GitHub setup."""
    monkeypatch.chdir(tmp_path)
    config = AppConfig.model_validate(
        {
            "platform": "github",
            "execution_mode": "local",
            "base_branch": "main",
            "remediation": {"target_branch": "main"},
            "github": {"labels": []},
            "state": {"path": ".zeroone-ops-state.json"},
        }
    )

    def unexpected_github_load() -> GitHubConnectionConfig:
        raise AssertionError("GitHub configuration should not load for local lifecycle failure.")

    def unexpected_gitlab_load() -> GitLabConnectionConfig:
        raise AssertionError("GitLab configuration should not load for GitHub lifecycle.")

    def unexpected_dependency(**kwargs: object) -> object:
        del kwargs
        raise AssertionError("Lifecycle dependencies should not build for local failure.")

    summary = WorkItemLifecycleWorkflow(
        config=config,
        dry_run=False,
        build_run_id=lambda: "run-1",
        build_context=build_workflow_run_context,
        is_gitlab_issue_mode=lambda _: False,
        load_github_config=unexpected_github_load,
        load_gitlab_config=unexpected_gitlab_load,
        build_dashboard_policy_view=unexpected_dependency,  # type: ignore[arg-type]
        publish_github_summary=unexpected_dependency,  # type: ignore[arg-type]
        publish_gitlab_summary=unexpected_dependency,  # type: ignore[arg-type]
    ).run_status_sync()

    assert summary.status == RunStatus.FAILED
    assert summary.message == (
        "[local] GitHub work-item lifecycle execution is only supported in CI mode. "
        "Use --dry-run locally."
    )
