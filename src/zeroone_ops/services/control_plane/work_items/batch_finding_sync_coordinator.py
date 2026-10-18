"""Internal batch sync composition; production routing remains single-finding until slice 3."""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.finding_batch_sync import BatchSyncContext, PreparedBatchWorkItem
from zeroone_ops.models.finding_sync import FindingSyncResult
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.services.control_plane.work_items.batch_finding_creation_service import (
    BatchFindingCreationService,
)
from zeroone_ops.services.control_plane.work_items.batch_finding_sync_projection import (
    BatchFindingSyncProjection,
)
from zeroone_ops.services.control_plane.work_items.batch_finding_sync_report import (
    BatchFindingSyncReport,
)
from zeroone_ops.services.control_plane.work_items.batch_finding_sync_storage import (
    BatchFindingSyncStorage,
    inventory_records,
)
from zeroone_ops.services.intake.finding_batch_ownership import build_finding_batch_ownership
from zeroone_ops.services.intake.finding_batch_promotion_service import FindingBatchPromotionService
from zeroone_ops.services.intake.finding_batch_reconciliation_service import (
    FindingBatchReconciliationService,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import FindingWorkflowPolicyService

LOGGER = logging.getLogger(__name__)


class BatchFindingSyncCoordinator:
    """Compose explicit reconciliation, planning, projection, creation, and reporting outcomes."""

    def __init__(
        self,
        storage: BatchFindingSyncStorage,
        *,
        clock: Callable[[], datetime] | None = None,
        logger: logging.Logger = LOGGER,
    ) -> None:
        """Compose focused shared services without performing I/O."""
        self.storage = storage
        self.clock = clock or (lambda: datetime.now(UTC))
        self.logger = logger
        policy = FindingWorkflowPolicyService()
        self.planner = FindingBatchPromotionService(policy)
        self.reconciliation = FindingBatchReconciliationService(policy)
        self.projection = BatchFindingSyncProjection(storage)
        self.creation = BatchFindingCreationService(storage, self.planner)

    def sync(
        self,
        *,
        repository_scope: str,
        findings: Sequence[NormalizedFinding],
        policy_state: PolicyState,
        managed_source_ids: set[str] | None = None,
        max_active_work_items: int = 10,
        max_findings_per_work_item: int = 10,
        source_priorities: Mapping[str, int] | None = None,
        persist: bool = True,
        run_id: str = "finding-sync",
    ) -> FindingSyncResult:
        """Reconcile internal batch work; dry runs allocate neither IDs nor persistence times."""
        records = tuple(
            record
            for record in inventory_records(
                self.storage.load_batch_inventory(repository_scope=repository_scope)
            )
            if record.work_item.source.repository_scope == repository_scope
        )
        inventory = _finding_inventory(findings)
        ownership = build_finding_batch_ownership(
            records=records, repository_scope=repository_scope
        )
        context = BatchSyncContext(
            repository_scope=repository_scope,
            policy_state=policy_state,
            run_id=run_id,
            now=self.clock() if persist else None,
            persist=persist,
            max_active_work_items=max_active_work_items,
            max_findings_per_work_item=max_findings_per_work_item,
            source_priorities=source_priorities,
        )

        prepared = [
            PreparedBatchWorkItem(record, record.work_item, False)
            if record.issue_number in ownership.conflict_issues
            else self.reconciliation.prepare(
                record, inventory, managed_source_ids or set(), context, ownership.suppressed
            )
            for record in records
        ]
        plan = self.planner.plan(
            findings=findings,
            records=[replace(entry.original, work_item=entry.work_item) for entry in prepared],
            policy_state=policy_state,
            repository_scope=repository_scope,
            max_active_work_items=max_active_work_items,
            max_findings_per_work_item=max_findings_per_work_item,
            source_priorities=source_priorities,
        )
        report = BatchFindingSyncReport(plan, prepared, repository_scope)
        if plan.conflicts:
            self.logger.warning(
                "Batch ownership is ambiguous; conflicting work retained",
                extra={
                    "issue_numbers": [c.issue_numbers for c in plan.conflicts],
                    "omitted_conflict_count": plan.omitted_conflict_count,
                },
            )

        selected = {
            unit.existing_record.issue_number: unit
            for unit in plan.selected_existing
            if unit.existing_record is not None
        }
        simulated = []
        for entry in prepared:
            if entry.original.issue_number in ownership.conflict_issues:
                continue
            desired = self.reconciliation.capacity_state(
                entry, entry.original.issue_number in selected, context
            )
            outcome = self.projection.project(
                repository_scope, entry.original, desired, persist=persist
            )
            if outcome.record is not None:
                simulated.append(replace(entry, work_item=desired))
            report.record_projection(outcome, selected.get(entry.original.issue_number))
            self._log_warnings(outcome.warnings)

        for unit in plan.selected_new:
            creation = self.creation.publish(unit, context, simulated)
            report.record_creation(creation)
            self._log_warnings(creation.warnings)

        return report.build(findings, policy_state)

    def _log_warnings(self, warnings: tuple[str, ...]) -> None:
        for warning in warnings:
            self.logger.warning(warning)


def _finding_inventory(
    findings: Sequence[NormalizedFinding],
) -> dict[tuple[str, str], NormalizedFinding]:
    inventory: dict[tuple[str, str], NormalizedFinding] = {}
    for finding in findings:
        key = finding.source_id, finding.finding_id
        if key in inventory and inventory[key] != finding:
            raise ValueError("Conflicting normalized findings share an identity.")
        inventory[key] = finding
    return inventory
