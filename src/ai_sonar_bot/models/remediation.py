"""Provider-neutral remediation models."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class RemediationProducerProfile:
    """Describe producer-specific prompt and publication behavior."""

    source_type: str
    source_display_name: str
    target_display_name: str
    item_reference_label: str
    analysis_system_prompt: str
    structured_edit_system_prompt: str
    mr_section_title: str
    diff_note: str


_DEFAULT_PROFILE = RemediationProducerProfile(
    source_type="generic",
    source_display_name="Remediation",
    target_display_name="remediation item",
    item_reference_label="Item reference",
    analysis_system_prompt=(
        "You analyze remediation items and return strictly structured JSON."
    ),
    structured_edit_system_prompt=(
        "You propose exact file edits for remediation items and return strictly "
        "structured JSON."
    ),
    mr_section_title="Remediation Target",
    diff_note="- Diff was rendered by the bot from a structured edit proposal.",
)

_SONARQUBE_PROFILE = RemediationProducerProfile(
    source_type="sonarqube",
    source_display_name="SonarQube",
    target_display_name="SonarQube issue",
    item_reference_label="Issue key",
    analysis_system_prompt=(
        "You analyze SonarQube issues and return strictly structured JSON."
    ),
    structured_edit_system_prompt=(
        "You propose exact file edits for SonarQube issues and return strictly "
        "structured JSON."
    ),
    mr_section_title="Remediation Target",
    diff_note="- Diff was rendered by the bot from a structured edit proposal.",
)


def remediation_profile_for(
    target: RemediationExecutionTarget,
) -> RemediationProducerProfile:
    """Return the producer profile for one remediation target."""
    if target.source_type == "sonarqube":
        return _SONARQUBE_PROFILE
    return _DEFAULT_PROFILE
