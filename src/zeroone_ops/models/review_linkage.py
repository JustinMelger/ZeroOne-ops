"""Non-persisted work-item lookup evidence for review context resolution."""

from dataclasses import dataclass

from zeroone_ops.models.work_item import WorkItemState


@dataclass(frozen=True)
class LinkedReviewWorkItem:
    """Carry parsed work-item authority and its provider issue URL without native transport."""

    work_item: WorkItemState
    issue_url: str | None
