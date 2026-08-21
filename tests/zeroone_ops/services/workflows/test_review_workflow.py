"""Tests for review workflow composition."""

from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.services.workflows.review_workflow import ReviewWorkflow
from zeroone_ops.services.workflows.workflow_run_context import build_workflow_run_context


def _config(*, platform: str, state_path: Path) -> AppConfig:
    """Build minimal provider-specific review configuration."""
    config: dict[str, object] = {
        "platform": platform,
        "base_branch": "main",
        "remediation": {"target_branch": "main"},
        "state": {"path": state_path},
    }
    if platform == "github":
        config["github"] = {"labels": []}
    else:
        config["gitlab"] = {"target_branch": "main", "labels": []}
    return AppConfig.model_validate(config)


def test_review_forwards_github_runtime_and_dry_run(tmp_path: Path, monkeypatch) -> None:
    """GitHub review keeps its event context and resolved dry-run behavior."""
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    class StubReviewRunner:
        def __init__(self, **kwargs: object) -> None:
            captured["init"] = kwargs

        def run(self, **kwargs: object) -> RunSummary:
            captured["run"] = kwargs
            return RunSummary(
                run_id="run-1",
                status=RunStatus.REVIEWED,
                message="[ci] Reviewed GitHub pull request.",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    monkeypatch.setattr(
        "zeroone_ops.services.workflows.review_workflow.ReviewRunner",
        StubReviewRunner,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.workflows.review_workflow.WorkflowTraceService.trace",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Dry-run review must not create an MLflow root trace.")
        ),
    )
    runtime_calls: list[AppConfig] = []
    config = _config(platform="github", state_path=tmp_path / ".zeroone-ops-state.json")
    workflow = ReviewWorkflow(
        config=config,
        dry_run=True,
        build_run_id=lambda: "run-1",
        build_context=build_workflow_run_context,
        build_platform_runtime=lambda current_config: (
            runtime_calls.append(current_config) or object(),
            "octo-org/octo-repo",
            42,
            "head-sha",
            None,
        ),
    )

    summary = workflow.run()

    assert summary.status is RunStatus.REVIEWED
    assert runtime_calls == [config]
    assert captured["run"] == {
        "repository_id": "octo-org/octo-repo",
        "current_change_request_number": 42,
        "triggered_head_sha": "head-sha",
        "record": captured["run"]["record"],
        "run_id": "run-1",
        "active_dry_run": True,
    }


def test_review_forwards_gitlab_runtime_with_dashboard_client(tmp_path: Path, monkeypatch) -> None:
    """GitLab review preserves merge-request and dashboard runtime inputs."""
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}
    review_client = object()
    dashboard_client = object()

    class StubReviewRunner:
        def __init__(self, **kwargs: object) -> None:
            captured["init"] = kwargs

        def run(self, **kwargs: object) -> RunSummary:
            captured["run"] = kwargs
            return RunSummary(
                run_id="run-1",
                status=RunStatus.NO_ISSUE,
                message="[ci] No merge request selected.",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    monkeypatch.setattr(
        "zeroone_ops.services.workflows.review_workflow.ReviewRunner",
        StubReviewRunner,
    )
    workflow = ReviewWorkflow(
        config=_config(platform="gitlab", state_path=tmp_path / ".zeroone-ops-state.json"),
        dry_run=False,
        build_run_id=lambda: "run-1",
        build_context=build_workflow_run_context,
        build_platform_runtime=lambda _: (
            review_client,
            "group/project",
            17,
            None,
            dashboard_client,
        ),
    )

    workflow.run()

    assert captured["init"] == {
        "repo_root": tmp_path,
        "config": workflow.config,
        "review_client": review_client,
        "dashboard_client": dashboard_client,
        "review_state_service": captured["init"]["review_state_service"],
    }
    assert captured["run"] == {
        "repository_id": "group/project",
        "current_change_request_number": 17,
        "triggered_head_sha": None,
        "record": captured["run"]["record"],
        "run_id": "run-1",
        "active_dry_run": False,
    }
