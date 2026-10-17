"""Immutable batch-owned copies of normalized finding evidence."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from zeroone_ops.models.finding import NormalizedFinding


class _FrozenBatchEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    def __deepcopy__(self, memo: dict[int, Any] | None = None) -> Self:
        """Reuse immutable evidence when containing work-item state is copied."""
        return self

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        """Validate replacements so copying cannot reintroduce mutable evidence."""
        if update:
            return type(self).model_validate(self.model_dump() | dict(update))
        return self


class BatchRemediationSnapshot(_FrozenBatchEvidence):
    """Preserve remediation scope and requirements without mutable nested lists."""

    category: str | None = None
    diagnostic_code: str | None = None
    validation_commands: tuple[str, ...] = ()
    expected_change: str | None = None
    constraints: str | None = None
    acceptance_criteria: tuple[str, ...] = ()


class BatchSourceMetadataSnapshot(_FrozenBatchEvidence):
    """Preserve JSON-compatible provenance as recursively immutable values."""

    native_id: str | None = None
    source_url: str | None = None
    attributes: Mapping[str, object] = Field(default_factory=lambda: MappingProxyType({}))

    @field_validator("attributes")
    @classmethod
    def _freeze_attributes(cls, attributes: Mapping[str, object]) -> Mapping[str, object]:
        return MappingProxyType({key: _freeze_metadata(value) for key, value in attributes.items()})

    @field_serializer("attributes")
    def _serialize_attributes(self, attributes: Mapping[str, object]) -> dict[str, object]:
        return {key: _serialize_metadata(value) for key, value in attributes.items()}


class BatchFindingSnapshot(_FrozenBatchEvidence):
    """Store a finding's original identity, diagnostic, and provenance immutably."""

    finding_id: str
    source_id: str
    severity: Literal["low", "medium", "high"]
    title: str
    summary: str
    repository_path: str
    line_start: int | None = None
    line_end: int | None = None
    region_hint: str | None = None
    remediation_context: BatchRemediationSnapshot = Field(default_factory=BatchRemediationSnapshot)
    source_metadata: BatchSourceMetadataSnapshot | None = None

    def to_finding(self) -> NormalizedFinding:
        """Materialize an isolated mutable finding for existing policy interfaces."""
        return NormalizedFinding.model_validate(self.model_dump(mode="json"))


def _freeze_metadata(value: object) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Batch provenance object keys must be strings.")
        return MappingProxyType({key: _freeze_metadata(nested) for key, nested in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_metadata(nested) for nested in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("Batch provenance must contain only JSON-compatible values.")


def _serialize_metadata(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _serialize_metadata(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_serialize_metadata(nested) for nested in value]
    return value
