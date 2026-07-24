"""Provider-local GitHub publication for promoted normalized findings."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.policy import PolicyState
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)


@dataclass(frozen=True)
class GitHubFindingSyncResult:
    """Summarize one GitHub finding publication pass."""

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


class GitHubFindingSyncService:
    """Publish policy-promoted normalized findings as GitHub work-item issues."""

    def __init__(
        self,
        *,
        work_item_service: GitHubWorkItemService,
        workflow_policy_service: FindingWorkflowPolicyService | None = None,
    ) -> None:
        """Initialize provider-local publication over shared finding policy."""
        self.work_item_service = work_item_service
        self.workflow_policy_service = workflow_policy_service or FindingWorkflowPolicyService()

    def sync(
        self,
        *,
        repository_id: str,
        findings: list[NormalizedFinding],
        policy_state: PolicyState,
        managed_source_ids: set[str] | None = None,
        persist: bool = True,
    ) -> GitHubFindingSyncResult:
        """Upsert only findings promoted by the shared workflow policy."""
        promoted_count = 0
        backlog_only_count = 0
        created_count = 0
        updated_count = 0
        unchanged_count = 0
        demoted_to_candidate_count = 0
        retained_protected_count = 0
        stale_demoted_to_candidate_count = 0
        stale_retained_protected_count = 0
        normalized_severity_counts: Counter[str] = Counter()
        backlog_reason_counts: Counter[str] = Counter()
        for finding in findings:
            normalized_severity_counts[finding.severity] += 1
            decision = self.workflow_policy_service.decide_promotion(
                finding=finding,
                policy_state=policy_state,
            )
            if decision.disposition != "promote":
                backlog_only_count += 1
                backlog_reason_counts[decision.reason] += 1
                if persist:
                    demotion = self._demote_if_safe(
                        finding=finding,
                        repository_id=repository_id,
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
            result = self.work_item_service.upsert_work_item(
                repository_id=repository_id,
                work_item=self._build_work_item(
                    finding=finding,
                    repository_id=repository_id,
                ),
            )
            if result.action == "created":
                created_count += 1
            elif result.action == "updated":
                updated_count += 1
            else:
                unchanged_count += 1
        if persist and managed_source_ids:
            stale_result = self._reconcile_stale_work_items(
                repository_id=repository_id,
                current_findings=findings,
                managed_source_ids=managed_source_ids,
            )
            stale_demoted_to_candidate_count = stale_result.demoted_count
            stale_retained_protected_count = stale_result.retained_count
            updated_count += stale_result.demoted_count
        return GitHubFindingSyncResult(
            promoted_count=promoted_count,
            backlog_only_count=backlog_only_count,
            created_count=created_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            demoted_to_candidate_count=demoted_to_candidate_count,
            retained_protected_count=retained_protected_count,
            stale_demoted_to_candidate_count=stale_demoted_to_candidate_count,
            stale_retained_protected_count=stale_retained_protected_count,
            normalized_severity_counts=dict(sorted(normalized_severity_counts.items())),
            enabled_severities=tuple(
                sorted(entry.severity for entry in policy_state.severity_policy if entry.enabled)
            ),
            backlog_reason_counts=dict(sorted(backlog_reason_counts.items())),
        )

    def _build_work_item(
        self,
        *,
        finding: NormalizedFinding,
        repository_id: str,
    ) -> WorkItemState:
        """Map one normalized finding into the existing work-item contract."""
        return WorkItemState(
            work_item_id=f"work-{uuid4().hex}",
            kind="remediation",
            status="approved",
            source=WorkItemSourceRef(
                source=finding.source_id,
                source_item_key=finding.finding_id,
                repository_scope=repository_id,
            ),
            summary=finding.title,
            detail=finding.summary,
            severity=finding.severity,
            file_path=finding.repository_path,
            line=finding.line_start,
        )

    def _demote_if_safe(
        self,
        *,
        finding: NormalizedFinding,
        repository_id: str,
    ) -> str | None:
        """Move an unlinked approved work item back to the candidate queue."""
        source = WorkItemSourceRef(
            source=finding.source_id,
            source_item_key=finding.finding_id,
            repository_scope=repository_id,
        )
        existing = self.work_item_service.find_open_work_item_by_source(
            repository_id=repository_id,
            kind="remediation",
            source=source,
        )
        if existing is None:
            return None
        return self._demote_work_item_if_safe(
            repository_id=repository_id,
            work_item=existing.work_item,
        )

    def _reconcile_stale_work_items(
        self,
        *,
        repository_id: str,
        current_findings: list[NormalizedFinding],
        managed_source_ids: set[str],
    ) -> _StaleWorkItemReconciliationResult:
        """Demote safely stale items only from complete, managed source inventories."""
        current_source_keys = {
            (finding.source_id, finding.finding_id) for finding in current_findings
        }
        demoted_count = 0
        retained_count = 0
        for existing in self.work_item_service.list_open_work_items(
            repository_id=repository_id,
        ):
            work_item = existing.work_item
            if work_item.source.repository_scope != repository_id:
                continue
            if work_item.source.source not in managed_source_ids:
                continue
            if (work_item.source.source, work_item.source.source_item_key) in current_source_keys:
                continue
            demotion = self._demote_work_item_if_safe(
                repository_id=repository_id,
                work_item=work_item,
            )
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
        repository_id: str,
        work_item: WorkItemState,
    ) -> Literal["demoted", "retained"] | None:
        """Demote only an unlinked approved work item without overriding active work."""
        if work_item.status == "approved" and work_item.linked_change_request is None:
            result = self.work_item_service.upsert_work_item(
                repository_id=repository_id,
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
