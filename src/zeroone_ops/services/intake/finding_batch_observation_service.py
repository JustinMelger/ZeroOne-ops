"""Refresh immutable batch observations without deciding lifecycle or execution."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.finding_batch import BatchMemberObservation, WorkItemBatch
from zeroone_ops.models.finding_batch_snapshot import BatchFindingSnapshot
from zeroone_ops.services.intake.finding_batch_ownership import finding_batch_group


@dataclass(frozen=True)
class BatchObservationRefresh:
    """Return valid batch state separately from rejected scope evidence."""

    batch: WorkItemBatch
    scope_mismatch_ids: tuple[str, ...]


def refresh_batch_observations(
    *,
    batch: WorkItemBatch,
    findings: Mapping[tuple[str, str], NormalizedFinding],
    managed_source_ids: set[str],
    run_id: str,
    now: datetime | None,
) -> BatchObservationRefresh:
    """Retain confirmed absence on unavailable scans; never persist out-of-scope evidence."""
    observations: list[BatchMemberObservation] = []
    mismatches: list[str] = []
    for prior in batch.observations:
        current = findings.get((batch.group.source_id, prior.finding_id))
        updates: dict[str, object] = {
            "sync_run_id": run_id,
            "observed_at": now or prior.observed_at,
            "freshness": "unknown",
        }
        if current is not None:
            if (
                finding_batch_group(repository_scope=batch.group.repository_scope, finding=current)
                != batch.group
            ):
                mismatches.append(prior.finding_id)
            else:
                updates.update(
                    last_confirmed_presence="detected",
                    freshness="current",
                    last_confirmed_sync_run_id=run_id,
                    last_confirmed_finding=BatchFindingSnapshot.model_validate(current),
                )
        elif batch.group.source_id in managed_source_ids:
            updates.update(
                last_confirmed_presence="absent",
                freshness="current",
                last_confirmed_sync_run_id=run_id,
            )
        observations.append(BatchMemberObservation.model_validate(prior.model_dump() | updates))

    refreshed = WorkItemBatch.model_validate(
        batch.model_dump() | {"observations": tuple(observations)}
    )
    return BatchObservationRefresh(batch=refreshed, scope_mismatch_ids=tuple(sorted(mismatches)))
