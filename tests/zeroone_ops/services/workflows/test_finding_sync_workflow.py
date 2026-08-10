"""Tests for finding-sync workflow route selection and lazy setup."""

from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.finding import FindingCollectionMetadata, FindingCollectionResult
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.intake.issue_intake import SyncIssueCollectionResult
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.workflows.finding_sync_workflow import FindingSyncWorkflow
from zeroone_ops.services.workflows.workflow_run_context import build_workflow_run_context


def _config(*, platform: str, issue_mode: bool = False) -> AppConfig:
    """Build minimal provider configuration for workflow routing tests."""
    config: dict[str, object] = {
        "platform": platform,
        "base_branch": "main",
        "state": {"path": ".zeroone-ops-state.json"},
    }
    if platform == "gitlab":
        config["gitlab"] = {
            "target_branch": "main",
            "control_plane_mode": "issues" if issue_mode else "dashboard",
        }
    return AppConfig.model_validate(config)


def _workflow(*, config: AppConfig) -> FindingSyncWorkflow:
    """Build workflow composition with provider loaders that must stay lazy."""

    def unexpected_provider_load() -> object:
        raise AssertionError("The unselected provider must not load configuration.")

    return FindingSyncWorkflow(
        config=config,
        dry_run=False,
        build_run_id=lambda: "run-1",
        build_context=build_workflow_run_context,
        is_gitlab_issue_mode=lambda candidate: (
            candidate.platform == "gitlab"
            and candidate.require_gitlab_config(reason="test").control_plane_mode == "issues"
        ),
        load_github_config=unexpected_provider_load,  # type: ignore[arg-type]
        load_gitlab_config=unexpected_provider_load,  # type: ignore[arg-type]
        build_dashboard_policy_view=unexpected_provider_load,  # type: ignore[arg-type]
        build_github_policy_issue_service=unexpected_provider_load,  # type: ignore[arg-type]
        build_gitlab_policy_issue_service=unexpected_provider_load,  # type: ignore[arg-type]
        publish_github_summary=unexpected_provider_load,  # type: ignore[arg-type]
        publish_gitlab_summary=unexpected_provider_load,  # type: ignore[arg-type]
    )


def test_run_selects_explicit_provider_route(monkeypatch) -> None:
    """GitHub and both GitLab modes retain visibly separate workflow routes."""
    expected = {
        "github": RunSummary(
            run_id="github",
            status=RunStatus.SYNCED,
            message="github",
            state_path=Path(".zeroone-ops-state.json"),
        ),
        "gitlab-dashboard": RunSummary(
            run_id="gitlab-dashboard",
            status=RunStatus.SYNCED,
            message="gitlab-dashboard",
            state_path=Path(".zeroone-ops-state.json"),
        ),
        "gitlab-issues": RunSummary(
            run_id="gitlab-issues",
            status=RunStatus.SYNCED,
            message="gitlab-issues",
            state_path=Path(".zeroone-ops-state.json"),
        ),
    }
    cases = (
        ("github", _config(platform="github"), "_run_github_issue_mode"),
        ("gitlab-dashboard", _config(platform="gitlab"), "_run_legacy_gitlab_dashboard"),
        ("gitlab-issues", _config(platform="gitlab", issue_mode=True), "_run_gitlab_issue_mode"),
    )

    for name, config, selected_route in cases:
        workflow = _workflow(config=config)
        monkeypatch.setattr(workflow, selected_route, lambda name=name: expected[name])

        assert workflow.run() == expected[name]


def test_github_empty_collection_does_not_load_provider_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An empty GitHub collection persists local state before provider wiring."""
    monkeypatch.chdir(tmp_path)
    workflow = _workflow(config=_config(platform="github"))
    collection = SyncIssueCollectionResult(
        finding_collection=FindingCollectionResult(
            findings=[],
            metadata=FindingCollectionMetadata(source_id="dashboard_sync"),
        ),
        issue_count=0,
        message="No configured finding sources collected dashboard-syncable findings.",
    )
    monkeypatch.setattr(workflow, "_collect", lambda context: collection)

    summary = workflow.run()

    assert summary.status.value == "no_issue"
    assert summary.message == f"[ci] {collection.message}"
