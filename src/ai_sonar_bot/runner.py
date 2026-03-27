"""Application runner.

This module coordinates the top-level execution flow for the bot.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.state import IssueState, RunRecord, RunStatus, utc_now
from ai_sonar_bot.services.state_store import StateStore
from ai_sonar_bot.settings import load_config

LOGGER = logging.getLogger(__name__)


@dataclass
class RunSummary:
    """Summarize a bot execution result.

    Attributes:
        run_id: Unique identifier for the execution.
        status: Terminal run status.
        message: Human-readable result summary.
        state_path: Path to the persisted state file.
    """

    run_id: str
    status: RunStatus
    message: str
    state_path: Path


def _build_run_id() -> str:
    """Build a unique run identifier.

    Returns:
        A timestamp-based run identifier with a random suffix.
    """
    timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{secrets.token_hex(4)}"


def _project_id_from_env() -> str | None:
    """Read the GitLab project ID override from the environment.

    Returns:
        The configured GitLab project ID, if present.
    """
    return os.environ.get("GITLAB_PROJECT_ID")


def _sonarqube_key_from_env() -> str | None:
    """Read the SonarQube project key override from the environment.

    Returns:
        The configured SonarQube project key, if present.
    """
    return os.environ.get("SONARQUBE_PROJECT_KEY")


def run(*, dry_run: bool = False) -> RunSummary:
    """Run the bot.

    Args:
        dry_run: Whether to execute in dry-run mode.

    Returns:
        A summary of the run result.
    """
    config = load_config()
    state_store = StateStore(
        config.state.path,
        base_branch=config.base_branch,
        gitlab_project_id=_project_id_from_env(),
        sonarqube_project_key=_sonarqube_key_from_env(),
    )
    state = state_store.load()

    run_id = _build_run_id()
    started_at = utc_now()
    record = RunRecord(
        run_id=run_id,
        status=RunStatus.STARTED,
        started_at=started_at,
        updated_at=started_at,
    )
    state_store.append_run(state, record)

    effective_dry_run = dry_run or config.dry_run
    if effective_dry_run:
        record.status = RunStatus.NO_ISSUE
        record.updated_at = utc_now()
        state_store.save(state)
        LOGGER.info("dry run complete", extra={"run_id": run_id})
        return RunSummary(
            run_id=run_id,
            status=record.status,
            message="Dry run complete. Integrations are not implemented yet.",
            state_path=config.state.path,
        )

    record.status = RunStatus.MANUAL
    record.error_message = "Provider integrations are not implemented yet."
    record.updated_at = utc_now()
    state.active_issue_key = None
    state_store.set_issue_state(
        state,
        issue_key="bootstrap",
        issue_state=IssueState(
            status=RunStatus.MANUAL.value,
            last_run_id=run_id,
            last_error=record.error_message,
        ),
    )
    state_store.save(state)

    return RunSummary(
        run_id=run_id,
        status=record.status,
        message=(
            "Scaffold created. SonarQube, LLM, and GitLab integrations still need "
            "implementation."
        ),
        state_path=config.state.path,
    )
