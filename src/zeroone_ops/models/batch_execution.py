"""Immutable batch execution scope and structural analysis accounting."""

from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from zeroone_ops.models.finding_batch_snapshot import BatchFindingSnapshot

type BatchAnalysisRejectionReason = Literal[
    "missing_coverage", "invalid_coverage", "unaddressable_members", "manual_classification"
]


@dataclass(frozen=True)
class BatchRejectedMemberView:
    """Keep bounded display evidence separate from executable member authority."""

    recorded_location: str
    explanation: str
    finding_reference: str


@dataclass(frozen=True)
class BatchAnalysisRejectionView:
    """Describe a pre-edit analysis stop without adding persisted workflow state."""

    summary: str
    members: tuple[BatchRejectedMemberView, ...]
    reason_code: BatchAnalysisRejectionReason
    omitted_member_count: int


class BatchUnaddressableMember(BaseModel):
    """Explain why one targeted finding cannot be addressed in this attempt."""

    model_config = ConfigDict(frozen=True)
    finding_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=600)

    @field_validator("reason")
    @classmethod
    def _require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Unaddressable member reasons must not be blank.")
        return value


class BatchAnalysisCoverage(BaseModel):
    """Account for every targeted member without establishing claim correctness."""

    model_config = ConfigDict(frozen=True)
    addressable_ids: tuple[str, ...] = ()
    unaddressable: tuple[BatchUnaddressableMember, ...] = ()


class BatchRejectedMember(BaseModel):
    """Keep bounded display references and reasons, never executable member IDs."""

    model_config = ConfigDict(frozen=True)
    finding_reference: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=600)


class BatchAnalysisRejection(BaseModel):
    """Persist diagnostic evidence separately from accepted analysis coverage."""

    model_config = ConfigDict(frozen=True)
    reason: BatchAnalysisRejectionReason
    members: tuple[BatchRejectedMember, ...] = Field(max_length=10)
    omitted_member_count: int = Field(default=0, ge=0)


class BatchAttemptEvidence(BaseModel):
    """Freeze the exact member mandate for one attempt and its subsequent retries."""

    model_config = ConfigDict(frozen=True)
    batch_id: str = Field(min_length=1)
    attempt_number: int = Field(ge=1)
    run_id: str | None = None
    members: tuple[BatchFindingSnapshot, ...] = Field(min_length=1)
    observation_run_ids: tuple[str, ...]
    coverage: BatchAnalysisCoverage | None = None

    @model_validator(mode="after")
    def _validate_members(self) -> Self:
        identities = [member.finding_id for member in self.members]
        if len(set(identities)) != len(identities):
            raise ValueError("Attempt member identities must be unique.")
        if self.coverage is not None:
            covered = [
                *self.coverage.addressable_ids,
                *(member.finding_id for member in self.coverage.unaddressable),
            ]
            if len(covered) != len(set(covered)) or set(covered) != set(identities):
                raise ValueError("Analysis coverage must exactly partition the attempt members.")
        return self
