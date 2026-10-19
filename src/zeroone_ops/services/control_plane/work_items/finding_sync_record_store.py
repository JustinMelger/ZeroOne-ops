"""Retain exact native snapshots and successful issue-state projections."""

from zeroone_ops.models.finding_sync import FindingSyncRecord
from zeroone_ops.models.work_item import WorkItemState


class FindingSyncRecordStore[NativeRecord]:
    """Own adapter-local snapshot identity without knowing provider transport."""

    def __init__(self) -> None:
        """Initialize empty snapshot and projection indexes without I/O."""
        self._snapshots: dict[int, tuple[FindingSyncRecord, NativeRecord]] = {}
        self._projection_state: dict[int, bool] = {}

    def remember(
        self,
        native: NativeRecord,
        *,
        work_item: WorkItemState,
        issue_number: int,
        issue_url: str,
        is_open: bool,
    ) -> FindingSyncRecord:
        """Keep the record alive so later reads cannot replace its native snapshot."""
        record = FindingSyncRecord(work_item, issue_number, issue_url, is_open)
        self._snapshots[id(record)] = (record, native)
        return record

    def native_record(self, record: FindingSyncRecord) -> NativeRecord:
        """Recover only this exact snapshot, not an equal or newer issue record."""
        return self._snapshots[id(record)][1]

    def record_issue_state(self, issue_number: int, *, is_open: bool) -> None:
        """Remember native closure state after a successful provider transition."""
        self._projection_state[issue_number] = is_open

    def projected_is_open(self, record: FindingSyncRecord) -> bool:
        """Use successful transitions without mutating an earlier read snapshot."""
        return self._projection_state.get(record.issue_number, record.is_open)
