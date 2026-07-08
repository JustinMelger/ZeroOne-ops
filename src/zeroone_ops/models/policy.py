"""Provider-neutral policy models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field

PolicySeverity = Literal["low", "medium", "high"]


class PolicyCommentSource(BaseModel):
    """Represent one provider comment that may contain a policy command."""

    id: int
    body: str | None = None
    author_username: str | None = None
    created_at: str | None = None


class PolicySeverityStateEntry(BaseModel):
    """Represent one canonical policy severity entry."""

    severity: PolicySeverity
    enabled: bool
    reason: str | None = None
    updated_at: datetime | None = None
    updated_by: str | None = None
    comment_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("comment_id", "note_id"),
        serialization_alias="note_id",
    )

    @property
    def note_id(self) -> int | None:
        """Return the legacy note ID alias."""
        return self.comment_id

    @note_id.setter
    def note_id(self, value: int | None) -> None:
        """Store the legacy note ID alias."""
        self.comment_id = value


class PolicyIssueClassStateEntry(BaseModel):
    """Represent one canonical issue-class policy entry."""

    source: str
    issue_key: str
    reason: str
    updated_at: datetime | None = None
    updated_by: str | None = None
    comment_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("comment_id", "note_id"),
        serialization_alias="note_id",
    )

    @property
    def note_id(self) -> int | None:
        """Return the legacy note ID alias."""
        return self.comment_id

    @note_id.setter
    def note_id(self, value: int | None) -> None:
        """Store the legacy note ID alias."""
        self.comment_id = value


class PolicyState(BaseModel):
    """Represent the canonical machine-owned policy state."""

    severity_policy: list[PolicySeverityStateEntry] = Field(default_factory=list)
    issue_class_exclusions: list[PolicyIssueClassStateEntry] = Field(default_factory=list)


class PolicyAction(BaseModel):
    """Represent one accepted policy action."""

    action_type: Literal[
        "show_policy",
        "enable_severity",
        "disable_severity",
        "exclude_issue_class",
        "include_issue_class",
    ]
    raw_command: str
    comment_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("comment_id", "note_id"),
    )
    author_username: str | None = None
    severity: PolicySeverity | None = None
    source: str | None = None
    issue_key: str | None = None

    @property
    def note_id(self) -> int | None:
        """Return the legacy note ID alias."""
        return self.comment_id

    @note_id.setter
    def note_id(self, value: int | None) -> None:
        """Store the legacy note ID alias."""
        self.comment_id = value


class PolicyActionParseResult(BaseModel):
    """Describe one policy-command parse outcome."""

    matched_prefix: bool
    accepted: bool
    raw_command: str
    error: str | None = None
    action: PolicyAction | None = None
    comment_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("comment_id", "note_id"),
    )

    @property
    def note_id(self) -> int | None:
        """Return the legacy note ID alias."""
        return self.comment_id

    @note_id.setter
    def note_id(self, value: int | None) -> None:
        """Store the legacy note ID alias."""
        self.comment_id = value
