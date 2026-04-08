"""Provider-neutral remediation models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RemediationWorkItem(BaseModel):
    """Represent one provider-neutral remediation candidate."""

    dashboard_item_id: str
    source_type: str
    source_ref: str
    title: str
    status: str
    message: str
    file_path: str
    line: int | None = None
    rule_id: str | None = None
    severity: str | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict)
    validation_commands: list[str] = Field(default_factory=list)
    expected_change: str | None = None
    constraints: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)


class RemediationExecutionTarget(BaseModel):
    """Represent one remediation candidate in the shared execution core."""

    item_id: str
    source_type: str
    source_ref: str
    title: str
    status: str
    message: str
    file_path: str
    line: int | None = None
    rule_id: str | None = None
    severity: str | None = None
    issue_type: str | None = None
    component: str | None = None
    project: str | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict)
    validation_commands: list[str] = Field(default_factory=list)
    expected_change: str | None = None
    constraints: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)
