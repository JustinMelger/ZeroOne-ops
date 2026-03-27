"""Application runner.

This module coordinates the top-level execution flow for the bot.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import AppState, IssueState, RunRecord, RunStatus, utc_now
from ai_sonar_bot.providers.llm_client import FixtureLLMClient
from ai_sonar_bot.providers.sonar_client import SonarClient, load_issues_fixture
from ai_sonar_bot.services.context_builder import ContextBuilder
from ai_sonar_bot.services.fix_generator import FixGenerator
from ai_sonar_bot.services.issue_selector import IssueSelector
from ai_sonar_bot.services.state_store import StateStore
from ai_sonar_bot.settings import SettingsError, load_config, load_sonarqube_connection_config

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
    repo_root = Path.cwd()
    selected_issue, issue_count, no_issue_message = _select_issue(
        repo_root=repo_root,
        config=config,
        dry_run=dry_run or config.dry_run,
        state=state,
        run_id=run_id,
    )

    if selected_issue is not None:
        issue_state = state.issues.get(selected_issue.key)
        attempt_count = issue_state.attempt_count if issue_state is not None else 0
        record.status = RunStatus.SELECTED
        record.issue_key = selected_issue.key
        record.updated_at = utc_now()
        state.active_issue_key = selected_issue.key
        state_store.set_issue_state(
            state,
            issue_key=selected_issue.key,
            issue_state=IssueState(
                status=RunStatus.SELECTED.value,
                last_run_id=run_id,
                attempt_count=attempt_count,
            ),
        )
        analysis_summary = _analyze_selected_issue(
            repo_root=repo_root,
            config=config,
            selected_issue=selected_issue,
            dry_run=dry_run or config.dry_run,
        )
        state_store.save(state)
        return RunSummary(
            run_id=run_id,
            status=record.status,
            message=(
                f"Selected SonarQube issue {selected_issue.key} in {selected_issue.file_path} "
                f"({selected_issue.rule}, {selected_issue.severity}). {analysis_summary}"
            ),
            state_path=config.state.path,
        )

    record.status = RunStatus.NO_ISSUE
    record.updated_at = utc_now()
    state.active_issue_key = None
    state_store.save(state)
    LOGGER.info("run complete", extra={"run_id": run_id, "issue_count": issue_count})
    return RunSummary(
        run_id=run_id,
        status=record.status,
        message=no_issue_message,
        state_path=config.state.path,
    )


def _select_issue(
    *,
    repo_root: Path,
    config: AppConfig,
    dry_run: bool,
    state: AppState,
    run_id: str,
) -> tuple[SonarIssue | None, int, str]:
    """Fetch and select one eligible SonarQube issue.

    Args:
        repo_root: Repository root path.
        config: Application configuration.
        dry_run: Whether the current run is executing in dry-run mode.
        state: Current application state.
        run_id: Active run identifier.

    Returns:
        A tuple of selected issue, fetched issue count, and fallback message.
    """
    issue_count = 0
    if dry_run and config.mock_sonar_issues_path is not None:
        issues = load_issues_fixture(config.mock_sonar_issues_path)
        issue_count = len(issues)
        existing_issues = [issue for issue in issues if _issue_file_exists(repo_root, issue)]
        selected_issue = IssueSelector(config).select(existing_issues, state)
        if selected_issue is None:
            return (
                None,
                issue_count,
                f"No eligible SonarQube issue found in fixture {config.mock_sonar_issues_path}.",
            )
        return selected_issue, issue_count, ""

    try:
        sonar_client = SonarClient(load_sonarqube_connection_config())
    except SettingsError:
        LOGGER.info("skipped SonarQube fetch", extra={"run_id": run_id})
        return None, issue_count, "No issue selected. SonarQube credentials not configured."

    issues = sonar_client.search_open_issues()
    issue_count = len(issues)
    existing_issues = [issue for issue in issues if _issue_file_exists(repo_root, issue)]
    selected_issue = IssueSelector(config).select(existing_issues, state)
    if selected_issue is None:
        return (
            None,
            issue_count,
            f"No eligible SonarQube issue found among {issue_count} open issues.",
        )
    return selected_issue, issue_count, ""


def _analyze_selected_issue(
    *,
    repo_root: Path,
    config: AppConfig,
    selected_issue: SonarIssue,
    dry_run: bool,
) -> str:
    """Analyze a selected issue when a dry-run analysis fixture is configured.

    Args:
        repo_root: Repository root path.
        config: Application configuration.
        selected_issue: Selected SonarQube issue.
        dry_run: Whether the current run is in dry-run mode.

    Returns:
        Human-readable analysis summary text.
    """
    context = ContextBuilder(repo_root, config).build(selected_issue)
    if context is None:
        return "Context unavailable for the selected issue."
    if not dry_run or config.mock_llm_analysis_path is None:
        return f"Context ready from lines {context.snippet.start_line}-{context.snippet.end_line}."

    analysis = FixGenerator(FixtureLLMClient(config.mock_llm_analysis_path)).analyze(
        selected_issue,
        context,
    )
    return (
        f"Analysis classification: {analysis.classification.value}. "
        f"Strategy: {analysis.proposed_strategy}"
    )


def _issue_file_exists(repo_root: Path, issue: SonarIssue) -> bool:
    """Check whether an issue points to an existing local file.

    Args:
        repo_root: Repository root path.
        issue: Candidate SonarQube issue.

    Returns:
        ``True`` if the file exists locally, otherwise ``False``.
    """
    return (repo_root / issue.file_path).exists()
