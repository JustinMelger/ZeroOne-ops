"""Provider-local GitLab publication for promoted normalized findings."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.work_item import (
    WorkItemCapacityDeferral,
    WorkItemKind,
    WorkItemPolicyDeferral,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.intake.finding_policy_reconciliation_service import (
    FindingPolicyReconciliationService,
)
from zeroone_ops.services.intake.finding_promotion_capacity_service import (
    FindingPromotionCapacityService,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitLabFindingSyncResult:
    """Summarize one GitLab finding publication pass."""

    promoted_count: int
    backlog_only_count: int
    created_count: int
    updated_count: int
    unchanged_count: int
    demoted_to_candidate_count: int
    retained_protected_count: int
    stale_demoted_to_candidate_count: int
    stale_retained_protected_count: int
    normalized_severity_counts: dict[str, int]
    enabled_severities: tuple[str, ...]
    backlog_reason_counts: dict[str, int]
    policy_deferred_count: int = 0
    capacity_deferred_count: int = 0
    policy_reactivated_count: int = 0
    no_longer_detected_count: int = 0
    projection_warning_count: int = 0


class GitLabFindingSyncService:
    """Publish policy-promoted normalized findings as GitLab work-item issues."""

    def __init__(
        self,
        *,
        work_item_service: GitLabWorkItemService,
        workflow_policy_service: FindingWorkflowPolicyService | None = None,
        promotion_capacity_service: FindingPromotionCapacityService | None = None,
        policy_reconciliation_service: FindingPolicyReconciliationService | None = None,
    ) -> None:
        """Initialize provider-local publication over shared finding policy."""
        self.work_item_service = work_item_service
        self.workflow_policy_service = workflow_policy_service or FindingWorkflowPolicyService()
        self.promotion_capacity_service = (
            promotion_capacity_service
            or FindingPromotionCapacityService(self.workflow_policy_service)
        )
        self.policy_reconciliation_service = (
            policy_reconciliation_service or FindingPolicyReconciliationService()
        )

    def sync(
        self,
        *,
        project_id: str,
        findings: list[NormalizedFinding],
        policy_state: PolicyState,
        managed_source_ids: set[str] | None = None,
        max_active_work_items: int = 10,
        persist: bool = True,
        run_id: str = "finding-sync",
    ) -> GitLabFindingSyncResult:
        """Upsert only findings promoted by the shared workflow policy."""
        promoted_count = 0
        backlog_only_count = 0
        created_count = 0
        updated_count = 0
        unchanged_count = 0
        demoted_to_candidate_count = 0
        retained_protected_count = 0
        normalized_severity_counts: Counter[str] = Counter()
        backlog_reason_counts: Counter[str] = Counter()
        projection_warning_count = 0
        policy_deferred_count = 0
        capacity_deferred_count = 0
        policy_reactivated_count = 0
        no_longer_detected_count = 0
        open_work_items = self.work_item_service.list_open_work_items(project_id=project_id)
        deferred_work_items = self.work_item_service.list_closed_policy_deferred_work_items(
            project_id=project_id
        )
        capacity_deferred_work_items = (
            self.work_item_service.list_closed_capacity_deferred_work_items(project_id=project_id)
        )
        deferred_work_items = [*deferred_work_items, *capacity_deferred_work_items]
        existing_by_identity: dict[
            tuple[str, str, str | None, WorkItemKind], GitLabWorkItemLookupResult
        ] = {}
        duplicate_identities: set[tuple[str, str, str | None, WorkItemKind]] = set()
        for lookup_result in open_work_items:
            identity_key = lookup_result.work_item.identity_key
            if identity_key in existing_by_identity:
                duplicate_identities.add(identity_key)
            else:
                existing_by_identity[identity_key] = lookup_result
        for identity_key in duplicate_identities:
            del existing_by_identity[identity_key]
        deferred_by_identity: dict[
            tuple[str, str, str | None, WorkItemKind], GitLabWorkItemLookupResult
        ] = {}
        ambiguous_deferred_identities: set[tuple[str, str, str | None, WorkItemKind]] = set()
        for lookup_result in deferred_work_items:
            identity_key = lookup_result.work_item.identity_key
            if (
                identity_key in deferred_by_identity
                or identity_key in existing_by_identity
                or identity_key in duplicate_identities
            ):
                ambiguous_deferred_identities.add(identity_key)
                continue
            deferred_by_identity[identity_key] = lookup_result
        for identity_key in ambiguous_deferred_identities:
            deferred_by_identity.pop(identity_key, None)
        capacity_plan = self.promotion_capacity_service.plan(
            findings=findings,
            policy_state=policy_state,
            open_work_items=self._capacity_work_items(
                findings=findings,
                policy_state=policy_state,
                open_work_items=[result.work_item for result in open_work_items],
                managed_source_ids=managed_source_ids,
                project_id=project_id,
            ),
            repository_scope=project_id,
            max_active_work_items=max_active_work_items,
        )
        for finding in findings:
            normalized_severity_counts[finding.severity] += 1
            decision = capacity_plan.decision_for(finding)
            existing_identity: tuple[str, str, str | None, WorkItemKind] = (
                finding.source_id,
                finding.finding_id,
                project_id,
                "remediation",
            )
            existing = existing_by_identity.get(existing_identity)
            deferred = deferred_by_identity.get(existing_identity)
            if (
                existing_identity in duplicate_identities
                or existing_identity in ambiguous_deferred_identities
            ):
                LOGGER.warning(
                    "GitLab finding sync skipped ambiguous work-item identity",
                    extra={"finding_id": finding.finding_id, "source_id": finding.source_id},
                )
                backlog_only_count += 1
                backlog_reason_counts["work_item_identity_ambiguous"] += 1
                continue
            existing_or_deferred = existing or deferred
            policy_decision = self.workflow_policy_service.decide_promotion(
                finding=finding,
                policy_state=policy_state,
            )
            reconciliation = self.policy_reconciliation_service.decide_for_current_finding(
                work_item=(
                    existing_or_deferred.work_item if existing_or_deferred is not None else None
                ),
                policy_eligible=policy_decision.disposition == "promote",
                promotion_eligible=decision.disposition == "promote",
            )
            if reconciliation.action == "defer":
                backlog_only_count += 1
                backlog_reason_counts[policy_decision.reason] += 1
                if persist:
                    outcome = self._defer_if_current(
                        project_id=project_id,
                        finding=finding,
                        run_id=run_id,
                    )
                    if outcome == "deferred":
                        policy_deferred_count += 1
                        updated_count += 1
                    elif outcome == "warning":
                        projection_warning_count += 1
                    elif outcome == "retained":
                        retained_protected_count += 1
                continue
            if reconciliation.action == "move_to_policy_deferred":
                backlog_only_count += 1
                backlog_reason_counts[policy_decision.reason] += 1
                if persist and deferred is not None:
                    if self._update_closed_deferral(
                        project_id=project_id,
                        existing=deferred,
                        status="policy_deferred",
                        run_id=run_id,
                    ):
                        policy_deferred_count += 1
                    else:
                        projection_warning_count += 1
                continue
            if reconciliation.action == "move_to_capacity_deferred":
                backlog_only_count += 1
                backlog_reason_counts[decision.reason] += 1
                if persist:
                    if existing is not None:
                        if self._defer_to_capacity_if_current(
                            project_id=project_id,
                            finding=finding,
                            run_id=run_id,
                        ):
                            capacity_deferred_count += 1
                            updated_count += 1
                    elif deferred is not None:
                        if self._update_closed_deferral(
                            project_id=project_id,
                            existing=deferred,
                            status="capacity_deferred",
                            run_id=run_id,
                        ):
                            capacity_deferred_count += 1
                        else:
                            projection_warning_count += 1
                continue
            if reconciliation.action == "retain_capacity_deferred":
                backlog_only_count += 1
                backlog_reason_counts[decision.reason] += 1
                continue
            if reconciliation.action == "retain_deferred":
                backlog_only_count += 1
                backlog_reason_counts[policy_decision.reason] += 1
                continue
            if reconciliation.action == "retain_protected":
                backlog_only_count += 1
                backlog_reason_counts[policy_decision.reason] += 1
                retained_protected_count += 1
                continue
            if reconciliation.action.startswith("reopen_"):
                if decision.disposition != "promote":
                    backlog_only_count += 1
                    backlog_reason_counts[decision.reason] += 1
                else:
                    promoted_count += 1
                if persist and deferred is not None:
                    work_item = self._build_promoted_work_item(
                        finding=finding,
                        project_id=project_id,
                        existing_work_item=deferred.work_item,
                    ).model_copy(
                        update={
                            "status": "approved",
                            "policy_deferral": None,
                            "capacity_deferral": None,
                        }
                    )
                    if self._reopen_and_update(
                        project_id=project_id,
                        existing=deferred,
                        work_item=work_item,
                    ):
                        policy_reactivated_count += 1
                        updated_count += 1
                    else:
                        projection_warning_count += 1
                continue
            if decision.disposition != "promote":
                backlog_only_count += 1
                backlog_reason_counts[decision.reason] += 1
                if persist:
                    demotion = self._demote_if_safe(
                        finding=finding,
                        project_id=project_id,
                        existing=existing,
                    )
                    if demotion == "demoted":
                        demoted_to_candidate_count += 1
                        updated_count += 1
                    elif demotion == "retained":
                        retained_protected_count += 1
                continue
            promoted_count += 1
            if not persist:
                continue
            work_item = self._build_promoted_work_item(
                finding=finding,
                project_id=project_id,
                existing_work_item=existing.work_item if existing is not None else None,
            )
            result = (
                self.work_item_service.update_existing_work_item(
                    project_id=project_id,
                    existing=existing,
                    work_item=work_item,
                )
                if existing is not None
                else self.work_item_service.upsert_work_item(
                    project_id=project_id,
                    work_item=work_item,
                )
            )
            if result.action == "created":
                created_count += 1
            elif result.action == "updated":
                updated_count += 1
            else:
                unchanged_count += 1
        stale_result = _StaleWorkItemReconciliationResult(
            demoted_count=0,
            retained_count=0,
            policy_deferred_count=0,
            projection_warning_count=0,
        )
        if persist and managed_source_ids:
            stale_result = self._reconcile_stale_work_items(
                project_id=project_id,
                current_findings=findings,
                managed_source_ids=managed_source_ids,
                open_work_items=open_work_items,
                policy_state=policy_state,
                run_id=run_id,
            )
            updated_count += stale_result.demoted_count
            updated_count += stale_result.policy_deferred_count
            policy_deferred_count += stale_result.policy_deferred_count
            projection_warning_count += stale_result.projection_warning_count
            current_source_keys = {(finding.source_id, finding.finding_id) for finding in findings}
            for deferred in deferred_work_items:
                if (
                    deferred.work_item.source.source in managed_source_ids
                    and (
                        deferred.work_item.source.source,
                        deferred.work_item.source.source_item_key,
                    )
                    not in current_source_keys
                ):
                    completed = deferred.work_item.model_copy(
                        update={
                            "status": "completed",
                            "resolution": "no_longer_detected",
                            "policy_deferral": None,
                            "capacity_deferral": None,
                        }
                    )
                    try:
                        result = self.work_item_service.update_existing_work_item(
                            project_id=project_id,
                            existing=deferred,
                            work_item=completed,
                        )
                    except Exception:
                        LOGGER.warning(
                            "GitLab deferred work-item completion projection failed",
                            exc_info=True,
                        )
                        projection_warning_count += 1
                    else:
                        if result.action == "updated":
                            no_longer_detected_count += 1
                            updated_count += 1
        return GitLabFindingSyncResult(
            promoted_count=promoted_count,
            backlog_only_count=backlog_only_count,
            created_count=created_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            demoted_to_candidate_count=demoted_to_candidate_count,
            retained_protected_count=retained_protected_count,
            stale_demoted_to_candidate_count=stale_result.demoted_count,
            stale_retained_protected_count=stale_result.retained_count,
            normalized_severity_counts=dict(sorted(normalized_severity_counts.items())),
            enabled_severities=tuple(
                sorted(entry.severity for entry in policy_state.severity_policy if entry.enabled)
            ),
            backlog_reason_counts=dict(sorted(backlog_reason_counts.items())),
            policy_deferred_count=policy_deferred_count,
            capacity_deferred_count=capacity_deferred_count,
            policy_reactivated_count=policy_reactivated_count,
            no_longer_detected_count=no_longer_detected_count,
            projection_warning_count=projection_warning_count,
        )

    def _defer_if_current(
        self, *, project_id: str, finding: NormalizedFinding, run_id: str
    ) -> Literal["deferred", "retained", "warning"]:
        """Re-read before closing so policy sync cannot overwrite active work."""
        source = WorkItemSourceRef(
            source=finding.source_id,
            source_item_key=finding.finding_id,
            repository_scope=project_id,
        )
        return self._defer_source_if_current(
            project_id=project_id,
            source=source,
            run_id=run_id,
        )

    def _defer_source_if_current(
        self,
        *,
        project_id: str,
        source: WorkItemSourceRef,
        run_id: str,
    ) -> Literal["deferred", "retained", "warning"]:
        """Close one still-safe work item after re-reading its authoritative state."""
        existing = self.work_item_service.find_open_work_item_by_source(
            project_id=project_id, kind="remediation", source=source
        )
        if existing is None:
            return "retained"
        work_item = existing.work_item
        if work_item.status not in {"candidate", "approved"} or work_item.linked_change_request:
            return "retained"
        deferred = work_item.model_copy(
            update={
                "status": "policy_deferred",
                "policy_deferral": WorkItemPolicyDeferral(
                    reason="policy_ineligible",
                    run_id=run_id,
                    occurred_at=datetime.now(UTC),
                ),
            }
        )
        try:
            self.work_item_service.update_existing_work_item(
                project_id=project_id, existing=existing, work_item=deferred
            )
            self.work_item_service.close_work_item_issue(
                project_id=project_id, issue_iid=existing.issue.iid
            )
        except Exception:
            LOGGER.warning("GitLab policy-deferred projection failed", exc_info=True)
            return "warning"
        return "deferred"

    def _reopen_and_update(
        self,
        *,
        project_id: str,
        existing: GitLabWorkItemLookupResult,
        work_item: WorkItemState,
    ) -> bool:
        """Reopen then render the active state, retaining repairable state on failure."""
        try:
            self.work_item_service.reopen_work_item_issue(
                project_id=project_id, issue_iid=existing.issue.iid
            )
            self.work_item_service.update_existing_work_item(
                project_id=project_id, existing=existing, work_item=work_item
            )
        except Exception:
            LOGGER.warning("GitLab policy-deferred reactivation projection failed", exc_info=True)
            return False
        return True

    def _defer_to_capacity_if_current(
        self, *, project_id: str, finding: NormalizedFinding, run_id: str
    ) -> bool:
        """Close a still-safe durable candidate outside active capacity."""
        source = WorkItemSourceRef(
            source=finding.source_id,
            source_item_key=finding.finding_id,
            repository_scope=project_id,
        )
        existing = self.work_item_service.find_open_work_item_by_source(
            project_id=project_id, kind="remediation", source=source
        )
        if (
            existing is None
            or existing.work_item.status != "candidate"
            or existing.work_item.linked_change_request is not None
        ):
            return False
        deferred = existing.work_item.model_copy(
            update={
                "status": "capacity_deferred",
                "capacity_deferral": WorkItemCapacityDeferral(
                    reason="promotion_capacity_exhausted",
                    run_id=run_id,
                    occurred_at=datetime.now(UTC),
                ),
            }
        )
        try:
            self.work_item_service.update_existing_work_item(
                project_id=project_id, existing=existing, work_item=deferred
            )
            self.work_item_service.close_work_item_issue(
                project_id=project_id, issue_iid=existing.issue.iid
            )
        except Exception:
            LOGGER.warning("GitLab capacity-deferred projection failed", exc_info=True)
            return False
        return True

    def _update_closed_deferral(
        self,
        *,
        project_id: str,
        existing: GitLabWorkItemLookupResult,
        status: Literal["policy_deferred", "capacity_deferred"],
        run_id: str,
    ) -> bool:
        """Update a closed deferred record without reopening its provider issue."""
        update: dict[str, object] = {
            "status": status,
            "policy_deferral": None,
            "capacity_deferral": None,
        }
        if status == "policy_deferred":
            update["policy_deferral"] = WorkItemPolicyDeferral(
                reason="policy_ineligible", run_id=run_id, occurred_at=datetime.now(UTC)
            )
        else:
            update["capacity_deferral"] = WorkItemCapacityDeferral(
                reason="promotion_capacity_exhausted", run_id=run_id, occurred_at=datetime.now(UTC)
            )
        try:
            self.work_item_service.update_existing_work_item(
                project_id=project_id,
                existing=existing,
                work_item=existing.work_item.model_copy(update=update),
            )
        except Exception:
            LOGGER.warning("GitLab deferred work-item projection failed", exc_info=True)
            return False
        return True

    def _capacity_work_items(
        self,
        *,
        findings: list[NormalizedFinding],
        policy_state: PolicyState,
        open_work_items: list[WorkItemState],
        managed_source_ids: set[str] | None,
        project_id: str,
    ) -> list[WorkItemState]:
        """Return the projected post-reconciliation state used for capacity planning."""
        current_findings = {
            (finding.source_id, finding.finding_id): finding for finding in findings
        }
        projected: list[WorkItemState] = []
        for work_item in open_work_items:
            if (
                work_item.status == "approved"
                and work_item.linked_change_request is None
                and self._is_safely_demotable_for_capacity(
                    work_item=work_item,
                    current_findings=current_findings,
                    policy_state=policy_state,
                    managed_source_ids=managed_source_ids,
                    project_id=project_id,
                )
            ):
                projected.append(work_item.model_copy(update={"status": "candidate"}))
            else:
                projected.append(work_item)
        return projected

    def _is_safely_demotable_for_capacity(
        self,
        *,
        work_item: WorkItemState,
        current_findings: dict[tuple[str, str], NormalizedFinding],
        policy_state: PolicyState,
        managed_source_ids: set[str] | None,
        project_id: str,
    ) -> bool:
        """Return whether normal sync reconciliation will safely demote one item."""
        if work_item.kind != "remediation" or work_item.source.repository_scope != project_id:
            return False
        key = (work_item.source.source, work_item.source.source_item_key)
        finding = current_findings.get(key)
        if finding is not None:
            return (
                self.workflow_policy_service.decide_promotion(
                    finding=finding,
                    policy_state=policy_state,
                ).disposition
                == "backlog_only"
            )
        return managed_source_ids is not None and work_item.source.source in managed_source_ids

    def _build_promoted_work_item(
        self,
        *,
        finding: NormalizedFinding,
        project_id: str,
        existing_work_item: WorkItemState | None,
    ) -> WorkItemState:
        """Preserve lifecycle state while refreshing one promoted finding."""
        proposed = WorkItemState(
            work_item_id=f"work-{uuid4().hex}",
            kind="remediation",
            status="approved",
            source=WorkItemSourceRef(
                source=finding.source_id,
                source_item_key=finding.finding_id,
                repository_scope=project_id,
            ),
            summary=finding.title,
            detail=finding.summary,
            severity=finding.severity,
            file_path=finding.repository_path,
            line=finding.line_start,
            remediation_context=finding.remediation_context,
        )
        if existing_work_item is None:
            return proposed
        status = (
            existing_work_item.status
            if existing_work_item.status in {"blocked", "dismissed", "in_progress"}
            else "approved"
        )
        return existing_work_item.model_copy(
            update={
                "status": status,
                "summary": proposed.summary,
                "detail": proposed.detail,
                "severity": proposed.severity,
                "file_path": proposed.file_path,
                "line": proposed.line,
                "remediation_context": proposed.remediation_context,
            }
        )

    def _demote_if_safe(
        self,
        *,
        finding: NormalizedFinding,
        project_id: str,
        existing: GitLabWorkItemLookupResult | None,
    ) -> str | None:
        """Move an unlinked approved work item back to the candidate queue."""
        if existing is None:
            return None
        return self._demote_work_item_if_safe(project_id=project_id, existing=existing)

    def _reconcile_stale_work_items(
        self,
        *,
        project_id: str,
        current_findings: list[NormalizedFinding],
        managed_source_ids: set[str],
        open_work_items: list[GitLabWorkItemLookupResult],
        policy_state: PolicyState,
        run_id: str,
    ) -> _StaleWorkItemReconciliationResult:
        """Demote safely stale items only from complete managed source inventories."""
        current_source_keys = {
            (finding.source_id, finding.finding_id) for finding in current_findings
        }
        demoted_count = 0
        retained_count = 0
        policy_deferred_count = 0
        projection_warning_count = 0
        for existing in open_work_items:
            work_item = existing.work_item
            if work_item.source.repository_scope != project_id:
                continue
            if work_item.source.source not in managed_source_ids:
                continue
            if (work_item.source.source, work_item.source.source_item_key) in current_source_keys:
                continue
            if not self.workflow_policy_service.is_work_item_eligible(
                work_item=work_item,
                policy_state=policy_state,
            ):
                outcome = self._defer_source_if_current(
                    project_id=project_id,
                    source=work_item.source,
                    run_id=run_id,
                )
                if outcome == "deferred":
                    policy_deferred_count += 1
                elif outcome == "retained":
                    retained_count += 1
                else:
                    projection_warning_count += 1
                continue
            demotion = self._demote_work_item_if_safe(project_id=project_id, existing=existing)
            if demotion == "demoted":
                demoted_count += 1
            elif demotion == "retained":
                retained_count += 1
        return _StaleWorkItemReconciliationResult(
            demoted_count=demoted_count,
            retained_count=retained_count,
            policy_deferred_count=policy_deferred_count,
            projection_warning_count=projection_warning_count,
        )

    def _demote_work_item_if_safe(
        self,
        *,
        project_id: str,
        existing: GitLabWorkItemLookupResult,
    ) -> Literal["demoted", "retained"] | None:
        """Demote only an unlinked approved item without overriding active work."""
        work_item = existing.work_item
        if work_item.status == "approved" and work_item.linked_change_request is None:
            result = self.work_item_service.update_existing_work_item(
                project_id=project_id,
                existing=existing,
                work_item=work_item.model_copy(update={"status": "candidate"}),
            )
            return "demoted" if result.action == "updated" else None
        if work_item.status in {"in_progress", "blocked"} or work_item.linked_change_request:
            return "retained"
        return None


@dataclass(frozen=True)
class _StaleWorkItemReconciliationResult:
    """Summarize safe stale-item transitions in one source inventory pass."""

    demoted_count: int
    retained_count: int
    policy_deferred_count: int
    projection_warning_count: int
