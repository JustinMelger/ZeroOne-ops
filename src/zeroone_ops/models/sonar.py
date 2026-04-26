"""SonarQube models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SonarImpact(BaseModel):
    """Represent a software-quality impact entry from SonarQube.

    Attributes:
        software_quality: Impacted software quality, such as maintainability.
        severity: Severity for the impacted quality.
    """

    software_quality: Literal["SECURITY", "RELIABILITY", "MAINTAINABILITY"] | str
    severity: Literal["BLOCKER", "HIGH", "MEDIUM", "LOW", "INFO"] | str


class SonarIssue(BaseModel):
    """Represent a SonarQube issue.

    Attributes:
        key: SonarQube issue key.
        rule: SonarQube rule identifier.
        severity: Issue severity.
        type: Issue type.
        status: SonarQube status.
        message: Human-readable issue message.
        component: SonarQube component identifier.
        project: SonarQube project key.
        file_path: Repository-relative file path.
        line: Line number if provided.
        effort: SonarQube effort estimate.
        tags: Associated SonarQube tags.
        impacts: Software-quality severities for newer SonarQube payloads.
        creation_date: Issue creation time if available.
    """

    key: str
    rule: str
    severity: str
    type: str
    status: str
    message: str
    component: str
    project: str
    file_path: str
    line: int | None = None
    effort: str | None = None
    tags: list[str] = Field(default_factory=list)
    impacts: list[SonarImpact] = Field(default_factory=list)
    creation_date: datetime | None = None

    def automation_severity(self) -> str:
        """Return the normalized automation severity band for the issue."""
        maintainability_severities = {
            impact.severity.upper()
            for impact in self.impacts
            if impact.software_quality.upper() == "MAINTAINABILITY"
        }
        if maintainability_severities:
            return _normalize_automation_severity(next(iter(sorted(maintainability_severities))))
        return _normalize_automation_severity(self.severity)

    def source_severity(self) -> str:
        """Return the raw source severity label for traceability."""
        return self.severity.upper()

    def matches_supported_severities(self, supported_severities: list[str]) -> bool:
        """Return whether the issue matches configured severity filters.

        This supports both newer MQR-style quality severities, such as
        maintainability `LOW`, and legacy severities like `MINOR`.

        Args:
            supported_severities: Configured severity filters.

        Returns:
            ``True`` when the issue should be considered eligible by severity.
        """
        normalized = {value.upper() for value in supported_severities}
        if not normalized:
            return True
        maintainability_severities = {
            impact.severity.upper()
            for impact in self.impacts
            if impact.software_quality.upper() == "MAINTAINABILITY"
        }
        if maintainability_severities and maintainability_severities & normalized:
            return True
        raw_severity = self.severity.upper()
        if raw_severity in normalized:
            return True
        return _legacy_to_modern_severity(self.severity) in normalized


def _normalize_automation_severity(severity: str) -> str:
    """Map raw SonarQube severities into automation severity bands."""
    normalized = _legacy_to_modern_severity(severity)
    return normalized.lower()


def _legacy_to_modern_severity(severity: str) -> str:
    """Map legacy SonarQube severities to UI-facing quality severities.

    Args:
        severity: Legacy issue severity from older API payloads.

    Returns:
        The normalized UI-facing severity level.
    """
    legacy = severity.upper()
    if legacy in {"BLOCKER", "CRITICAL"}:
        return "HIGH"
    if legacy == "MAJOR":
        return "MEDIUM"
    if legacy in {"MINOR", "INFO"}:
        return "LOW"
    return legacy
