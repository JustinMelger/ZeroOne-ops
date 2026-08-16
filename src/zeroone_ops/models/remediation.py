"""Provider-neutral remediation models."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from pydantic import BaseModel, Field

STATIC_ANALYSIS_FIX_CATEGORY = "static_analysis_fix"
_LEGACY_REMEDIATION_CATEGORY_ALIASES = {
    "code_smell_fix": STATIC_ANALYSIS_FIX_CATEGORY,
    "lint_fix": STATIC_ANALYSIS_FIX_CATEGORY,
}


def normalize_remediation_category(category: str | None) -> str | None:
    """Return the canonical shared remediation category for one item."""
    if category is None:
        return None
    return _LEGACY_REMEDIATION_CATEGORY_ALIASES.get(category, category)


def is_remediation_eligible_category(category: str | None) -> bool:
    """Return whether one shared remediation category is currently supported."""
    return normalize_remediation_category(category) == STATIC_ANALYSIS_FIX_CATEGORY


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
    remediation_category: str | None = None
    issue_type: str | None = None
    component: str | None = None
    project: str | None = None
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
    work_item_url: str | None = None
    line: int | None = None
    rule_id: str | None = None
    severity: str | None = None
    remediation_category: str | None = None
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
    """Describe producer-specific operator-facing presentation."""

    source_type: str
    source_display_name: str
    target_display_name: str
    item_reference_label: str
    mr_section_title: str


_DEFAULT_PROFILE = RemediationProducerProfile(
    source_type="generic",
    source_display_name="Remediation",
    target_display_name="remediation item",
    item_reference_label="Item reference",
    mr_section_title="Remediation Target",
)

_SONARQUBE_PROFILE = RemediationProducerProfile(
    source_type="sonarqube",
    source_display_name="SonarQube",
    target_display_name="SonarQube issue",
    item_reference_label="Issue key",
    mr_section_title="Remediation Target",
)


def remediation_profile_for(
    target: RemediationExecutionTarget,
) -> RemediationProducerProfile:
    """Return the producer profile for one remediation target."""
    if target.source_type == "sonarqube":
        return _SONARQUBE_PROFILE
    return replace(
        _DEFAULT_PROFILE,
        source_type=target.source_type,
        source_display_name=remediation_source_display_name(target.source_type),
    )


def remediation_source_display_name(source_type: str) -> str:
    """Return a concise human label for a normalized finding source."""
    known_labels = {
        "sonarqube": "SonarQube",
        "ruff-sarif": "Ruff SARIF",
        "mypy-sarif": "MyPy SARIF",
    }
    if source_type in known_labels:
        return known_labels[source_type]
    return source_type.replace("-", " ").replace("_", " ").title()
