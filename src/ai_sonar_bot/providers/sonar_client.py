"""SonarQube API client.

This module will provide SonarQube REST integration for issue retrieval.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ai_sonar_bot.models.config import SonarQubeConnectionConfig
from ai_sonar_bot.models.sonar import SonarIssue


class SonarClientError(RuntimeError):
    """Raised when SonarQube communication fails."""


class SonarClient:
    """SonarQube REST client.

    Args:
        config: SonarQube connection settings.
        http_client: Optional injected HTTP client for testing.
    """

    def __init__(
        self,
        config: SonarQubeConnectionConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        """Initialize the SonarQube client.

        Args:
            config: SonarQube connection settings.
            http_client: Optional injected HTTP client for testing.
        """
        self.config = config
        self._http_client = http_client or httpx.Client(
            base_url=str(config.url).rstrip("/"),
            auth=(config.token, ""),
            timeout=30.0,
        )

    def search_open_issues(self) -> list[SonarIssue]:
        """Fetch open issues from SonarQube.

        Returns:
            Open SonarQube issues for the configured project.
        """
        response = self._http_client.get(
            "/api/issues/search",
            params={
                "projects": self.config.project_key,
                "statuses": "OPEN,REOPENED,CONFIRMED",
                "ps": self.config.page_size,
            },
        )
        payload = _parse_json_response(response)
        issues = payload.get("issues")
        if not isinstance(issues, list):
            raise SonarClientError("Unexpected SonarQube response: missing issues list.")
        return [_normalize_issue(item) for item in issues]

    def get_issue(self, issue_key: str) -> SonarIssue:
        """Fetch a specific SonarQube issue.

        Args:
            issue_key: SonarQube issue key.

        Returns:
            The requested SonarQube issue.
        """
        response = self._http_client.get("/api/issues/show", params={"issue": issue_key})
        payload = _parse_json_response(response)
        issue = payload.get("issue")
        if not isinstance(issue, dict):
            raise SonarClientError("Unexpected SonarQube response: missing issue object.")
        return _normalize_issue(issue)


def load_issues_fixture(path: Path) -> list[SonarIssue]:
    """Load SonarQube issues from a local JSON fixture.

    Args:
        path: Path to the fixture file.

    Returns:
        Normalized SonarQube issues from the fixture.

    Raises:
        SonarClientError: If the file is missing or invalid.
    """
    if not path.exists():
        raise SonarClientError(f"SonarQube fixture file not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SonarClientError(f"SonarQube fixture file is invalid JSON: {path}") from error

    if not isinstance(payload, dict):
        raise SonarClientError("Unexpected SonarQube fixture payload.")

    issues = payload.get("issues")
    if not isinstance(issues, list):
        raise SonarClientError("Unexpected SonarQube fixture: missing issues list.")

    return [_normalize_issue(item) for item in issues if isinstance(item, dict)]


def _parse_json_response(response: httpx.Response) -> dict[str, Any]:
    """Validate and parse a SonarQube JSON response.

    Args:
        response: HTTP response to parse.

    Returns:
        Parsed JSON dictionary.

    Raises:
        SonarClientError: If the response is unsuccessful or invalid.
    """
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        message = f"SonarQube request failed with status {error.response.status_code}."
        raise SonarClientError(message) from error

    try:
        payload = response.json()
    except ValueError as error:
        raise SonarClientError("SonarQube returned invalid JSON.") from error

    if not isinstance(payload, dict):
        raise SonarClientError("Unexpected SonarQube response payload.")
    return payload


def _normalize_issue(payload: dict[str, Any]) -> SonarIssue:
    """Normalize a raw SonarQube issue payload.

    Args:
        payload: Raw SonarQube issue payload.

    Returns:
        Normalized SonarQube issue model.
    """
    component = _required_string(payload, "component")
    project = _required_string(payload, "project")
    return SonarIssue(
        key=_required_string(payload, "key"),
        rule=_required_string(payload, "rule"),
        severity=_required_string(payload, "severity"),
        type=_required_string(payload, "type"),
        status=_required_string(payload, "status"),
        message=_required_string(payload, "message"),
        component=component,
        project=project,
        file_path=_normalize_component_path(component=component, project=project),
        line=_optional_int(payload.get("line")),
        effort=_optional_string(payload.get("effort")),
        tags=_optional_string_list(payload.get("tags")),
        creation_date=_parse_datetime(_optional_string(payload.get("creationDate"))),
    )


def _normalize_component_path(*, component: str, project: str) -> str:
    """Normalize SonarQube component paths to repository-relative paths.

    Args:
        component: SonarQube component value.
        project: SonarQube project key.

    Returns:
        Repository-relative POSIX path.
    """
    prefix = f"{project}:"
    relative = component[len(prefix) :] if component.startswith(prefix) else component
    return relative.lstrip("/")


def _required_string(payload: dict[str, Any], key: str) -> str:
    """Read a required string from a payload.

    Args:
        payload: Source payload.
        key: Key to read.

    Returns:
        The required string value.

    Raises:
        SonarClientError: If the value is missing or invalid.
    """
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    raise SonarClientError(f"Unexpected SonarQube response: missing {key!r}.")


def _optional_string(value: Any) -> str | None:
    """Return an optional string value.

    Args:
        value: Raw value.

    Returns:
        The string value or ``None``.
    """
    return value if isinstance(value, str) and value else None


def _optional_int(value: Any) -> int | None:
    """Return an optional integer value.

    Args:
        value: Raw value.

    Returns:
        The integer value or ``None``.
    """
    return value if isinstance(value, int) else None


def _optional_string_list(value: Any) -> list[str]:
    """Return a list of string values.

    Args:
        value: Raw value.

    Returns:
        The filtered list of strings.
    """
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse SonarQube date strings.

    Args:
        value: SonarQube date string.

    Returns:
        Parsed datetime or ``None``.
    """
    if value is None:
        return None
    normalized = value.replace("Z", "+00:00")
    if len(normalized) >= 5 and normalized[-5] in {"+", "-"} and normalized[-3] != ":":
        normalized = f"{normalized[:-2]}:{normalized[-2:]}"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None
