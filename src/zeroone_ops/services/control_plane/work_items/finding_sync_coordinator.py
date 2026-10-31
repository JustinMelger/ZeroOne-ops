"""Coordinate finding ownership, batch promotion, and provider projection."""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.finding_batch_sync import (
    BatchProjectionOutcome,
    BatchSyncContext,
    PreparedBatchWorkItem,
)
from zeroone_ops.models.finding_sync import FindingSyncResult
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.work_item import is_active_remediation_status
from zeroone_ops.services.control_plane.work_items.batch_finding_creation_service import (
    BatchFindingCreationService,
)
from zeroone_ops.services.control_plane.work_items.batch_finding_sync_projection import (
    BatchFindingSyncProjection,
)
from zeroone_ops.services.control_plane.work_items.batch_finding_sync_report import (
    BatchFindingSyncReport,
)
from zeroone_ops.services.control_plane.work_items.finding_sync_inventory import (
    inventory_records,
)
from zeroone_ops.services.control_plane.work_items.finding_sync_storage import FindingSyncStorage
from zeroone_ops.services.intake.finding_batch_ownership import build_finding_batch_ownership
from zeroone_ops.services.intake.finding_batch_promotion_service import FindingBatchPromotionService
from zeroone_ops.services.intake.finding_batch_reconciliation_service import (
    FindingBatchReconciliationService,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import FindingWorkflowPolicyService

LOGGER = logging.getLogger(__name__)


class FindingSyncCoordinator:
    """Compose explicit reconciliation, planning, projection, creation, and reporting outcomes."""

    def __init__(
        self,
        storage: FindingSyncStorage,
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
        max_findings_per_work_item: int = 5,
        source_priorities: Mapping[str, int] | None = None,
        persist: bool = True,
        run_id: str = "finding-sync",
    ) -> FindingSyncResult:
        """Reconcile finding work; dry runs allocate neither IDs nor persistence times."""
        records = tuple(
            record
            for record in inventory_records(
                self.storage.load_inventory(repository_scope=repository_scope)
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
        prepared, releases = self._release_capacity(prepared, context)
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
            if entry.original.issue_number in releases:
                outcome = releases[entry.original.issue_number]
                if outcome.record is not None:
                    simulated.append(entry)
                report.record_projection(outcome, None)
                continue

            desired = self.reconciliation.capacity_state(
                entry, entry.original.issue_number in selected, context
            )
            outcome = self.projection.project(
                repository_scope, entry.original, desired, persist=persist
            )
            if outcome.record is not None:
                simulated.append(replace(entry, work_item=outcome.record.work_item))
            report.record_projection(outcome, selected.get(entry.original.issue_number))
            self._log_warnings(outcome.warnings)

        for unit in plan.selected_new:
            creation = self.creation.publish(unit, context, simulated)
            report.record_creation(creation)
            self._log_warnings(creation.warnings)

        return report.build(findings, policy_state)

    def _release_capacity(
        self, prepared: Sequence[PreparedBatchWorkItem], context: BatchSyncContext
    ) -> tuple[list[PreparedBatchWorkItem], dict[int, BatchProjectionOutcome]]:
        """Free slots only after confirmed releases; uncertain writes retain reservations."""
        reconciled = []
        outcomes = {}
        for entry in prepared:
            if is_active_remediation_status(
                entry.original.work_item.status
            ) and not is_active_remediation_status(entry.work_item.status):
                outcome = self.projection.project(
                    context.repository_scope,
                    entry.original,
                    entry.work_item,
                    persist=context.persist,
                )
                outcomes[entry.original.issue_number] = outcome
                self._log_warnings(outcome.warnings)
                authoritative = outcome.record or entry.original
                reconciled.append(replace(entry, work_item=authoritative.work_item))
            else:
                reconciled.append(entry)
        return reconciled, outcomes

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
