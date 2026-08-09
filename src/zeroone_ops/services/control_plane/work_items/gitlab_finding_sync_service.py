"""Provider-local GitLab publication for promoted normalized findings."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.work_item import WorkItemKind, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.intake.finding_promotion_capacity_service import (
    FindingPromotionCapacityService,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)


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


class GitLabFindingSyncService:
    """Publish policy-promoted normalized findings as GitLab work-item issues."""

    def __init__(
        self,
        *,
        work_item_service: GitLabWorkItemService,
        workflow_policy_service: FindingWorkflowPolicyService | None = None,
        promotion_capacity_service: FindingPromotionCapacityService | None = None,
    ) -> None:
        """Initialize provider-local publication over shared finding policy."""
        self.work_item_service = work_item_service
        self.workflow_policy_service = workflow_policy_service or FindingWorkflowPolicyService()
        self.promotion_capacity_service = (
            promotion_capacity_service
            or FindingPromotionCapacityService(self.workflow_policy_service)
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
        open_work_items = (
            self.work_item_service.list_open_work_items(project_id=project_id) if persist else []
        )
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
        stale_result = _StaleWorkItemReconciliationResult(demoted_count=0, retained_count=0)
        if persist and managed_source_ids:
            stale_result = self._reconcile_stale_work_items(
                project_id=project_id,
                current_findings=findings,
                managed_source_ids=managed_source_ids,
                open_work_items=open_work_items,
            )
            updated_count += stale_result.demoted_count
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
        )

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
    ) -> _StaleWorkItemReconciliationResult:
        """Demote safely stale items only from complete managed source inventories."""
        current_source_keys = {
            (finding.source_id, finding.finding_id) for finding in current_findings
        }
        demoted_count = 0
        retained_count = 0
        for existing in open_work_items:
            work_item = existing.work_item
            if work_item.source.repository_scope != project_id:
                continue
            if work_item.source.source not in managed_source_ids:
                continue
            if (work_item.source.source, work_item.source.source_item_key) in current_source_keys:
                continue
            demotion = self._demote_work_item_if_safe(project_id=project_id, existing=existing)
            if demotion == "demoted":
                demoted_count += 1
            elif demotion == "retained":
                retained_count += 1
        return _StaleWorkItemReconciliationResult(
            demoted_count=demoted_count,
            retained_count=retained_count,
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
