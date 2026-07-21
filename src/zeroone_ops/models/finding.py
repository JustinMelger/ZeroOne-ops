"""Provider-neutral finding ingestion models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RemediationContext(BaseModel):
    """Represent bounded remediation-relevant context for one finding."""

    category: str | None = None
    diagnostic_code: str | None = None
    validation_commands: list[str] = Field(default_factory=list)
    expected_change: str | None = None
    constraints: str | None = None
    acceptance_criteria: list[str] = Field(default_factory=list)


class FindingSourceMetadata(BaseModel):
    """Represent optional source-local metadata for one normalized finding."""

    native_id: str | None = None
    source_url: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class NormalizedFinding(BaseModel):
    """Represent one provider-neutral finding after source-local normalization."""

    finding_id: str
    source_id: str
    severity: Literal["low", "medium", "high"]
    title: str
    summary: str
    repository_path: str
    line_start: int | None = None
    line_end: int | None = None
    region_hint: str | None = None
    remediation_context: RemediationContext = Field(default_factory=RemediationContext)
    source_metadata: FindingSourceMetadata | None = None


class FindingCollectionMetadata(BaseModel):
    """Represent bounded collection-level metadata for one ingestion run."""

    source_id: str
    source_revision: str | None = None
    artifact_reference: str | None = None
    warnings: list[str] = Field(default_factory=list)
    statistics: dict[str, int] = Field(default_factory=dict)


class FindingCollectionResult(BaseModel):
    """Represent the shared result returned by one finding ingestor."""

    findings: list[NormalizedFinding] = Field(default_factory=list)
    metadata: FindingCollectionMetadata
