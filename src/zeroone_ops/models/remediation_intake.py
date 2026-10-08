"""Provider-neutral records and outcomes for remediation intake."""

from dataclasses import dataclass
from datetime import datetime

from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.work_item import WorkItemState


@dataclass(frozen=True)
class RemediationIntakeRecord:
    """Represent parsed work and the issue metadata needed for intake."""

    work_item: WorkItemState
    issue_number: int
    issue_url: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class RemediationIntakeOutcome:
    """Capture shared selection and an optional persistent claim."""

    selected_record: RemediationIntakeRecord | None
    selected_target: RemediationExecutionTarget | None
    item_count: int
