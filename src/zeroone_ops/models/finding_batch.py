"""Typed frozen membership and observation contracts for future batching."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zeroone_ops.models.finding_batch_snapshot import BatchFindingSnapshot


class FindingBatchGroup(BaseModel):
    """Identify one repository-local file, source, and diagnostic rule."""

    model_config = ConfigDict(frozen=True)

    repository_scope: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)

    @field_validator("repository_scope", "source_id", "rule_id")
    @classmethod
    def _require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Batch scope values must not be blank.")
        return value

    @field_validator("file_path")
    @classmethod
    def _require_canonical_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in value
            or ":" in path.parts[0]
            or path.as_posix() != value
        ):
            raise ValueError("Batch paths must be canonical repository-relative paths.")
        return value

    @property
    def key(self) -> tuple[str, str, str, str]:
        """Return the stable comparison and sorting key."""
        return self.repository_scope, self.file_path, self.source_id, self.rule_id


class BatchMemberObservation(BaseModel):
    """Keep confirmed presence separate from the latest scan's freshness."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    finding_id: str = Field(min_length=1)
    last_confirmed_presence: Literal["detected", "absent"]
    freshness: Literal["current", "unknown"]
    sync_run_id: str = Field(min_length=1)
    observed_at: datetime
    last_confirmed_sync_run_id: str | None = None
    last_confirmed_finding: BatchFindingSnapshot | None = None


class WorkItemBatch(BaseModel):
    """Preserve complete original members and their latest observations."""

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    group: FindingBatchGroup
    members: tuple[BatchFindingSnapshot, ...] = Field(min_length=1)
    observations: tuple[BatchMemberObservation, ...]

    @field_validator("observations")
    @classmethod
    def _copy_observations(
        cls, observations: tuple[BatchMemberObservation, ...]
    ) -> tuple[BatchMemberObservation, ...]:
        return tuple(observation.model_copy(deep=True) for observation in observations)

    @model_validator(mode="after")
    def _validate_membership(self) -> Self:
        member_ids = [member.finding_id for member in self.members]
        observation_ids = [observation.finding_id for observation in self.observations]
        if any(not identifier.strip() for identifier in member_ids):
            raise ValueError("Batch member identities must not be blank.")
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("Batch members must have unique finding identities.")
        if len(observation_ids) != len(set(observation_ids)) or set(observation_ids) != set(
            member_ids
        ):
            raise ValueError("Batch observations must match the member identities exactly.")
        for member in self.members:
            self._validate_scope(member)
        for observation in self.observations:
            evidence = observation.last_confirmed_finding
            if evidence is not None:
                if evidence.finding_id != observation.finding_id:
                    raise ValueError("Observation evidence must match its member identity.")
                self._validate_scope(evidence)
        return self

    def _validate_scope(self, finding: BatchFindingSnapshot) -> None:
        if (
            finding.source_id != self.group.source_id
            or finding.repository_path != self.group.file_path
            or finding.remediation_context.diagnostic_code != self.group.rule_id
        ):
            raise ValueError("Every batch member must match the group's source, file, and rule.")


@dataclass(frozen=True)
class FindingBatchIdentity:
    """Carry one explicitly assigned immutable batch identity."""

    work_item_id: str
    source_item_key: str
