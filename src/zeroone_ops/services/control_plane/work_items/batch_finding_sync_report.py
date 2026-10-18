"""Aggregate explicit batch-sync outcomes without provider access or workflow decisions."""

from collections import Counter
from collections.abc import Sequence

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.finding_batch_promotion import (
    FindingBatchMemberIdentity,
    FindingBatchPromotionPlan,
    FindingBatchPromotionUnit,
)
from zeroone_ops.models.finding_batch_sync import (
    BatchCreationOutcome,
    BatchProjectionOutcome,
    PreparedBatchWorkItem,
)
from zeroone_ops.models.finding_sync import FindingSyncResult
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.services.intake.finding_batch_ownership import retains_finding_batch_ownership


class BatchFindingSyncReport:
    """Own run-local counters; transport helpers never receive mutable reporting state."""

    def __init__(
        self, plan: FindingBatchPromotionPlan, prepared: Sequence[PreparedBatchWorkItem], scope: str
    ) -> None:
        """Seed per-finding reasons and the existing bounded ambiguity warning count."""
        self.prepared = tuple(prepared)
        self._counts: Counter[str] = Counter(warnings=int(bool(plan.conflicts)))
        dispositions = {decision.identity: decision.reason for decision in plan.decisions}
        for entry in prepared:
            if entry.work_item.batch and entry.selection_reason:
                for member in entry.work_item.batch.members:
                    identity: FindingBatchMemberIdentity = (
                        scope,
                        member.source_id,
                        member.finding_id,
                        "remediation",
                    )
                    if dispositions.get(identity) == "owned":
                        dispositions[identity] = entry.selection_reason
        self._reasons: Counter[str] = Counter(
            reason for reason in dispositions.values() if reason != "selected"
        )

    def record_projection(
        self, outcome: BatchProjectionOutcome, selected: FindingBatchPromotionUnit | None
    ) -> None:
        """Count successful transitions/previews, not partially failed provider writes."""
        self._counts["warnings"] += len(outcome.warnings)
        if outcome.write_action is not None:
            self._counts[outcome.write_action] += 1
        if outcome.record is None:
            if selected is not None:
                self._reasons["projection_failed"] += len(selected.members)
            return

        status = outcome.record.work_item.status
        if status != outcome.previous_status:
            self._counts[status] += 1
            if status == "approved" and outcome.previous_status in {
                "policy_deferred",
                "capacity_deferred",
            }:
                self._counts["reactivated"] += 1
        if selected is not None:
            self._counts["promoted"] += 1
            self._counts["members"] += len(selected.members)

    def record_creation(self, outcome: BatchCreationOutcome) -> None:
        """Retain finding-unit backlog counts separately from work-item write counts."""
        self._counts["warnings"] += len(outcome.warnings)
        self._reasons.update(outcome.backlog_reason_counts)
        if outcome.write_action is not None:
            self._counts[outcome.write_action] += 1
        if outcome.selected_member_count:
            self._counts["promoted"] += 1
            self._counts["members"] += outcome.selected_member_count

    def build(
        self, findings: Sequence[NormalizedFinding], policy: PolicyState
    ) -> FindingSyncResult:
        """Return the established result contract without changing selection meaning."""
        return FindingSyncResult(
            promoted_count=self._counts["promoted"],
            backlog_only_count=sum(self._reasons.values()),
            created_count=self._counts["created"],
            updated_count=self._counts["updated"],
            unchanged_count=self._counts["unchanged"],
            demoted_to_candidate_count=0,
            retained_protected_count=sum(
                not entry.reconcilable and retains_finding_batch_ownership(entry.original)
                for entry in self.prepared
            ),
            stale_demoted_to_candidate_count=0,
            stale_retained_protected_count=0,
            normalized_severity_counts=dict(Counter(f.severity for f in findings)),
            enabled_severities=tuple(
                sorted(entry.severity for entry in policy.severity_policy if entry.enabled)
            ),
            backlog_reason_counts=dict(self._reasons),
            policy_deferred_count=self._counts["policy_deferred"],
            capacity_deferred_count=self._counts["capacity_deferred"],
            policy_reactivated_count=self._counts["reactivated"],
            no_longer_detected_count=self._counts["completed"],
            projection_warning_count=self._counts["warnings"],
            selected_member_count=self._counts["members"],
            selection_blocked_count=self._counts["blocked"],
            unknown_freshness_member_count=sum(
                observation.freshness == "unknown"
                for entry in self.prepared
                if entry.work_item.batch and retains_finding_batch_ownership(entry.original)
                for observation in entry.work_item.batch.observations
            ),
        )
