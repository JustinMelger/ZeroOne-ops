"""Tests for repository-local workflow composition."""

from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.services.workflows.workflow_run_context import build_workflow_run_context


def test_build_workflow_run_context_resolves_dry_run_without_provider_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Local context setup does not require GitHub or GitLab credentials."""
    monkeypatch.chdir(tmp_path)
    config = AppConfig.model_validate(
        {
            "platform": "github",
            "base_branch": "main",
            "state": {"path": ".zeroone-ops-state.json"},
        }
    )

    context = build_workflow_run_context(config=config, run_id="run-1", dry_run=True)

    assert context.run_id == "run-1"
    assert context.repo_root == tmp_path
    assert context.active_dry_run is True
    assert context.state_store.path == Path(".zeroone-ops-state.json")
    assert context.state.repository.base_branch == "main"
