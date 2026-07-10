"""Provider-neutral work-item models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

WorkItemKind = Literal["remediation"]
WorkItemStatus = Literal[
    "candidate",
    "approved",
    "in_progress",
    "blocked",
    "completed",
    "dismissed",
]


class ChangeRequestRef(BaseModel):
    """Represent one linked provider-backed change request."""

    number: int
    web_url: str


class WorkItemSourceRef(BaseModel):
    """Represent the stable source identity for one work item."""

    source: str
    source_item_key: str
    repository_scope: str | None = None


class WorkItemState(BaseModel):
    """Represent one canonical provider-neutral work item."""

    work_item_id: str
    kind: WorkItemKind
    status: WorkItemStatus
    source: WorkItemSourceRef
    summary: str
    severity: str | None = None
    file_path: str | None = None
    line: int | None = None
    linked_change_request: ChangeRequestRef | None = None
    created_by_system: Literal["zeroone_ops"] = "zeroone_ops"

    @property
    def identity_key(self) -> tuple[str, str, str | None, WorkItemKind]:
        """Return the stable identity key for open-item reuse."""
        return (
            self.source.source,
            self.source.source_item_key,
            self.source.repository_scope,
            self.kind,
        )
