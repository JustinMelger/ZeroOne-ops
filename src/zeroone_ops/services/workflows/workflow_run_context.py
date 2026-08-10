"""Shared repository-local dependencies for one workflow invocation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.state import AppState
from zeroone_ops.services.shared.run_state_service import RunStateService
from zeroone_ops.services.shared.state_store import StateStore
from zeroone_ops.settings import (
    load_gitlab_project_id_override,
    load_sonarqube_project_key_override,
)


@dataclass(frozen=True)
class WorkflowRunContext:
    """Hold shared local state for one workflow without loading provider credentials."""

    config: AppConfig
    repo_root: Path
    state_store: StateStore
    state: AppState
    run_state_service: RunStateService
    run_id: str
    active_dry_run: bool


def build_workflow_run_context(
    *,
    config: AppConfig,
    run_id: str,
    dry_run: bool,
    repo_root: Path | None = None,
) -> WorkflowRunContext:
    """Build shared local workflow dependencies without provider-side effects."""
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=load_gitlab_project_id_override(),
        sonarqube_project_key=load_sonarqube_project_key_override(),
    )
    state = state_store.load()
    return WorkflowRunContext(
        config=config,
        repo_root=repo_root or Path.cwd(),
        state_store=state_store,
        state=state,
        run_state_service=RunStateService(config=config, state_store=state_store, state=state),
        run_id=run_id,
        active_dry_run=dry_run or config.dry_run,
    )
