"""SonarQube models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    creation_date: datetime | None = None
