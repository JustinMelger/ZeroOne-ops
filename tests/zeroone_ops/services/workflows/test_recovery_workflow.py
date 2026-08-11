"""Tests for recovery workflow routing and lazy provider setup."""

from pathlib import Path

from zeroone_ops.models.config import AppConfig, GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.workflows.recovery_workflow import RecoveryWorkflow
from zeroone_ops.services.workflows.workflow_run_context import build_workflow_run_context


def test_github_missing_event_context_does_not_load_provider_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Recovery reports a local event-context failure before GitHub setup."""
    monkeypatch.chdir(tmp_path)
    config = AppConfig.model_validate(
        {
            "platform": "github",
            "base_branch": "main",
            "remediation": {"target_branch": "main"},
            "github": {"labels": []},
            "state": {"path": ".zeroone-ops-state.json"},
        }
    )

    def unexpected_github_load() -> GitHubConnectionConfig:
        raise AssertionError("GitHub configuration should not load without event context.")

    def unexpected_gitlab_load() -> GitLabConnectionConfig:
        raise AssertionError("GitLab configuration should not load for GitHub recovery.")

    def unexpected_dependency(**kwargs: object) -> object:
        del kwargs
        raise AssertionError("Recovery dependencies should not build without event context.")

    summary = RecoveryWorkflow(
        config=config,
        dry_run=False,
        publish_operational_summary=True,
        build_run_id=lambda: "run-1",
        build_context=build_workflow_run_context,
        is_gitlab_issue_mode=lambda _: False,
        load_github_config=unexpected_github_load,
        load_gitlab_config=unexpected_gitlab_load,
        load_github_issue_number=lambda: None,
        load_github_comment_id=lambda: None,
        build_dashboard_policy_view=unexpected_dependency,  # type: ignore[arg-type]
        build_github_policy_issue_service=unexpected_dependency,  # type: ignore[arg-type]
        build_gitlab_policy_issue_service=unexpected_dependency,  # type: ignore[arg-type]
        build_github_recovery_runner=unexpected_dependency,  # type: ignore[arg-type]
        publish_github_summary=unexpected_dependency,  # type: ignore[arg-type]
        publish_gitlab_summary=unexpected_dependency,  # type: ignore[arg-type]
    ).run()

    assert summary.status == RunStatus.FAILED
    assert summary.message == "[ci] GitHub recovery requires an issue_comment workflow event."
