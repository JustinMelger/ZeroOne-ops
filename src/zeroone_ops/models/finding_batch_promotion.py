"""Provider-neutral outputs of dormant batch promotion planning."""

from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.finding_batch import FindingBatchGroup
from zeroone_ops.models.finding_sync import FindingSyncRecord

type FindingBatchMemberIdentity = tuple[str, str, str, Literal["remediation"]]
type FindingBatchDecisionReason = Literal[
    "selected",
    "owned",
    "dismissed",
    "severity_disabled",
    "issue_class_excluded",
    "group_reserved",
    "batch_overflow",
    "promotion_capacity_exhausted",
    "ownership_conflict",
    "batch_scope_mismatch",
]


@dataclass(frozen=True)
class FindingBatchFindingDecision:
    """Explain one input finding's disposition without mixing finding/unit counts."""

    identity: FindingBatchMemberIdentity
    reason: FindingBatchDecisionReason


@dataclass(frozen=True)
class FindingBatchPromotionUnit:
    """Represent an ID-less new proposal or an existing durable selection."""

    group: FindingBatchGroup | None
    members: tuple[NormalizedFinding, ...]
    existing_record: FindingSyncRecord | None = None


@dataclass(frozen=True)
class FindingBatchOwnershipConflict:
    """Bound references to conflicting authoritative ownership."""

    issue_numbers: tuple[int, ...]
    omitted_issue_count: int


@dataclass(frozen=True)
class FindingBatchPromotionPlan:
    """Report selections, per-finding reasons, and bounded ownership conflicts."""

    selected_new: tuple[FindingBatchPromotionUnit, ...]
    selected_existing: tuple[FindingBatchPromotionUnit, ...]
    decisions: tuple[FindingBatchFindingDecision, ...]
    conflicts: tuple[FindingBatchOwnershipConflict, ...]
    active_work_item_count: int
    omitted_conflict_count: int = 0
