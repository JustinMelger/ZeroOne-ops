"""Application settings loader.

This module reads repository-local configuration and applies environment-based
overrides for runtime execution.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ai_sonar_bot.models.config import AppConfig, SonarQubeConnectionConfig


class SettingsError(RuntimeError):
    """Raised when configuration cannot be loaded."""


def _load_environment_file() -> None:
    """Load environment variables from a local ``.env`` file if present."""
    load_dotenv(override=False)


def _config_path() -> Path:
    """Return the config file path.

    Returns:
        The resolved path to the runtime config file.
    """
    return Path(os.environ.get("AI_SONAR_BOT_CONFIG", ".ai-sonar-bot.json"))


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


def load_config() -> AppConfig:
    """Load and validate application configuration.

    Returns:
        The validated application configuration.
    """
    _load_environment_file()
    data = _load_json_file(_config_path())
    env_base_branch = os.environ.get("AI_SONAR_BOT_BASE_BRANCH")
    env_mock_llm_analysis_path = os.environ.get("AI_SONAR_BOT_MOCK_LLM_ANALYSIS_PATH")
    env_mock_sonar_issues_path = os.environ.get("AI_SONAR_BOT_MOCK_SONAR_ISSUES_PATH")
    env_state_path = os.environ.get("AI_SONAR_BOT_STATE_PATH")

    if env_base_branch:
        data["base_branch"] = env_base_branch
    if env_mock_llm_analysis_path:
        data["mock_llm_analysis_path"] = env_mock_llm_analysis_path
    if env_mock_sonar_issues_path:
        data["mock_sonar_issues_path"] = env_mock_sonar_issues_path
    if env_state_path:
        state = dict(data.get("state", {}))
        state["path"] = env_state_path
        data["state"] = state

    return AppConfig.model_validate(data)


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
