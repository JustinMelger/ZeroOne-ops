"""Application settings loader.

This module reads repository-local configuration and applies environment-based
overrides for runtime execution.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

from zeroone_ops.models.config import (
    AppConfig,
    GitHubConnectionConfig,
    GitLabConnectionConfig,
    OpenAIConnectionConfig,
    SonarQubeConnectionConfig,
)


class SettingsError(RuntimeError):
    """Raised when configuration cannot be loaded."""


LOGGER = logging.getLogger(__name__)


def _load_environment_file() -> None:
    """Load environment variables from a local ``.env`` file if present."""
    load_dotenv(dotenv_path=Path(".env"), override=False)


def _first_env(*names: str) -> str | None:
    """Return the first set environment variable value from ``names``."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _config_path() -> Path:
    """Return the config file path.

    Returns:
        The resolved path to the runtime config file.
    """
    explicit_path = _first_env("ZEROONE_OPS_CONFIG")
    if explicit_path is not None:
        return Path(explicit_path)

    preferred_path = Path(".zeroone-ops.json")
    if preferred_path.exists():
        return preferred_path
    return preferred_path


def _load_json_file(path: Path) -> dict[str, Any]:
    """Load a JSON file from disk.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON content as a dictionary.

    Raises:
        SettingsError: If the file does not exist.
    """
    if not path.exists():
        raise SettingsError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return dict(json.load(handle))


def _warn_deprecated_config_fields(data: dict[str, Any]) -> None:
    """Log migration guidance for still-supported compatibility fields."""
    deprecated_fields = (
        ("review", "platform", "platform"),
        ("gitlab", "target_branch", "remediation.target_branch"),
        ("remediation", "supported_severities", "remediation.bootstrap_severities"),
    )
    for section, field, replacement in deprecated_fields:
        section_data = data.get(section)
        if isinstance(section_data, dict) and field in section_data:
            LOGGER.warning(
                "Deprecated config field `%s.%s` is a compatibility alias. "
                "Use `%s` for new configuration; it will be removed in a future major release.",
                section,
                field,
                replacement,
            )


def load_config() -> AppConfig:
    """Load and validate application configuration.

    Returns:
        The validated application configuration.
    """
    _load_environment_file()
    data = _load_json_file(_config_path())
    env_execution_mode = _first_env("ZEROONE_OPS_EXECUTION_MODE")
    env_base_branch = _first_env("ZEROONE_OPS_BASE_BRANCH")
    env_apply_patch_in_dry_run = _first_env("ZEROONE_OPS_APPLY_PATCH_IN_DRY_RUN")
    env_write_solution_artifacts_in_ci = _first_env("ZEROONE_OPS_WRITE_SOLUTION_ARTIFACTS_IN_CI")
    env_mock_llm_analysis_path = _first_env("ZEROONE_OPS_MOCK_LLM_ANALYSIS_PATH")
    env_mock_llm_edit_path = _first_env("ZEROONE_OPS_MOCK_LLM_EDIT_PATH")
    env_openai_solution_output_path = _first_env("ZEROONE_OPS_OPENAI_SOLUTION_OUTPUT_PATH")
    env_mock_sonar_issues_path = _first_env("ZEROONE_OPS_MOCK_SONAR_ISSUES_PATH")
    env_state_path = _first_env("ZEROONE_OPS_STATE_PATH")

    if env_execution_mode:
        data["execution_mode"] = env_execution_mode
    if env_base_branch:
        data["base_branch"] = env_base_branch
    if env_apply_patch_in_dry_run:
        data["apply_patch_in_dry_run"] = env_apply_patch_in_dry_run.lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if env_write_solution_artifacts_in_ci:
        data["write_solution_artifacts_in_ci"] = env_write_solution_artifacts_in_ci.lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if env_openai_solution_output_path:
        data["openai_solution_output_path"] = env_openai_solution_output_path
    if env_mock_llm_analysis_path:
        data["mock_llm_analysis_path"] = env_mock_llm_analysis_path
    if env_mock_llm_edit_path:
        data["mock_llm_edit_path"] = env_mock_llm_edit_path
    if env_mock_sonar_issues_path:
        sonarqube = dict(data.get("sonarqube", {}))
        sonarqube["mock_issues_path"] = env_mock_sonar_issues_path
        data["sonarqube"] = sonarqube
    if env_state_path:
        state = dict(data.get("state", {}))
        state["path"] = env_state_path
        data["state"] = state

    _warn_deprecated_config_fields(data)

    try:
        return AppConfig.model_validate(data)
    except ValidationError as error:
        raise SettingsError(f"Invalid configuration: {error}") from error


def load_sonarqube_connection_config() -> SonarQubeConnectionConfig:
    """Load SonarQube connection settings from the environment.

    Returns:
        Validated SonarQube connection settings.

    Raises:
        SettingsError: If a required SonarQube environment variable is missing.
    """
    _load_environment_file()
    required = {
        "SONARQUBE_URL": os.environ.get("SONARQUBE_URL"),
        "SONARQUBE_TOKEN": os.environ.get("SONARQUBE_TOKEN"),
        "SONARQUBE_PROJECT_KEY": os.environ.get("SONARQUBE_PROJECT_KEY"),
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        names = ", ".join(missing)
        raise SettingsError(f"Missing required SonarQube environment variables: {names}")

    return SonarQubeConnectionConfig(
        url=required["SONARQUBE_URL"] or "",
        token=required["SONARQUBE_TOKEN"] or "",
        project_key=required["SONARQUBE_PROJECT_KEY"] or "",
    )


def load_openai_connection_config() -> OpenAIConnectionConfig:
    """Load OpenAI connection settings from the environment.

    Returns:
        Validated OpenAI connection settings.

    Raises:
        SettingsError: If a required OpenAI environment variable is missing.
    """
    _load_environment_file()
    required = {
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "OPENAI_MODEL": os.environ.get("OPENAI_MODEL"),
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        names = ", ".join(missing)
        raise SettingsError(f"Missing required OpenAI environment variables: {names}")

    return OpenAIConnectionConfig(
        api_key=required["OPENAI_API_KEY"] or "",
        model=required["OPENAI_MODEL"] or "",
        base_url=os.environ.get("OPENAI_BASE_URL"),
        mlflow_enabled=(os.environ.get("ZEROONE_MLFLOW_ENABLED") or "").lower()
        in {"1", "true", "yes", "on"},
        mlflow_tracking_uri=os.environ.get("MLFLOW_TRACKING_URI"),
        mlflow_experiment_name=os.environ.get("MLFLOW_EXPERIMENT_NAME"),
        mlflow_experiment_id=os.environ.get("MLFLOW_EXPERIMENT_ID"),
    )


def load_gitlab_connection_config() -> GitLabConnectionConfig:
    """Load GitLab connection settings from the environment.

    Returns:
        Validated GitLab connection settings.

    Raises:
        SettingsError: If a required GitLab environment variable is missing.
    """
    _load_environment_file()
    project_id = os.environ.get("GITLAB_PROJECT_ID") or os.environ.get("CI_PROJECT_ID")
    required = {
        "GITLAB_URL": os.environ.get("GITLAB_URL"),
        "GITLAB_TOKEN": os.environ.get("GITLAB_TOKEN"),
        "GITLAB_PROJECT_ID": project_id,
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        names = ", ".join(missing)
        raise SettingsError(f"Missing required GitLab environment variables: {names}")

    return GitLabConnectionConfig(
        url=required["GITLAB_URL"] or "",
        token=required["GITLAB_TOKEN"] or "",
        project_id=project_id or "",
    )


def load_github_connection_config() -> GitHubConnectionConfig:
    """Load GitHub connection settings from the environment.

    Returns:
        Validated GitHub connection settings.

    Raises:
        SettingsError: If a required GitHub environment variable is missing.
    """
    _load_environment_file()
    required = {
        "GITHUB_TOKEN": os.environ.get("GITHUB_TOKEN"),
        "GITHUB_REPOSITORY": os.environ.get("GITHUB_REPOSITORY"),
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        names = ", ".join(missing)
        raise SettingsError(f"Missing required GitHub environment variables: {names}")

    return GitHubConnectionConfig(
        api_url=os.environ.get("GITHUB_API_URL") or "https://api.github.com",
        server_url=os.environ.get("GITHUB_SERVER_URL") or "https://github.com",
        token=required["GITHUB_TOKEN"] or "",
        repository=required["GITHUB_REPOSITORY"] or "",
    )


def load_current_change_request_number() -> int | None:
    """Load the current change-request number from CI context when present."""
    _load_environment_file()
    raw_value = os.environ.get("CI_MERGE_REQUEST_IID")
    if raw_value is None or raw_value == "":
        return None
    try:
        return int(raw_value)
    except ValueError as error:
        raise SettingsError("CI_MERGE_REQUEST_IID must be an integer when set.") from error


def load_current_github_pull_request_number() -> int | None:
    """Load the current GitHub pull-request number from workflow context when present."""
    payload = _load_github_event_payload()
    if payload is None:
        return None

    number = payload.get("number")
    if number is None:
        pull_request = payload.get("pull_request")
        if not isinstance(pull_request, dict):
            return None
        number = pull_request.get("number")
    if not isinstance(number, int):
        raise SettingsError("GitHub pull_request.number must be an integer when set.")
    return number


def load_current_github_pull_request_head_sha() -> str | None:
    """Load the triggering GitHub pull-request head SHA from workflow context when present."""
    payload = _load_github_event_payload()
    if payload is None:
        return None

    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, dict):
        return None
    head = pull_request.get("head")
    if not isinstance(head, dict):
        return None
    head_sha = head.get("sha")
    if head_sha is None:
        return None
    if not isinstance(head_sha, str):
        raise SettingsError("GitHub pull_request.head.sha must be a string when set.")
    return head_sha


def _load_github_event_payload() -> dict[str, Any] | None:
    """Load the current GitHub workflow event payload when present."""
    _load_environment_file()
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return None

    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except OSError as error:
        raise SettingsError(f"Could not read GITHUB_EVENT_PATH payload: {error}") from error
    except json.JSONDecodeError as error:
        raise SettingsError("GITHUB_EVENT_PATH does not contain valid JSON.") from error

    if not isinstance(payload, dict):
        raise SettingsError("GITHUB_EVENT_PATH payload must be a JSON object.")
    return payload


def load_gitlab_project_id_override() -> str | None:
    """Load the GitLab project ID override for state metadata when present."""
    _load_environment_file()
    return os.environ.get("GITLAB_PROJECT_ID")


def load_sonarqube_project_key_override() -> str | None:
    """Load the SonarQube project key override for state metadata when present."""
    _load_environment_file()
    return os.environ.get("SONARQUBE_PROJECT_KEY")
