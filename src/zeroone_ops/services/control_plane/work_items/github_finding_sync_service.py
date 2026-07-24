"""Provider-local GitHub publication for promoted normalized findings."""

from __future__ import annotations

from dataclasses import dataclass
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
        persist: bool = True,
    ) -> GitHubFindingSyncResult:
        """Upsert only findings promoted by the shared workflow policy."""
        promoted_count = 0
        backlog_only_count = 0
        created_count = 0
        updated_count = 0
        unchanged_count = 0
        for finding in findings:
            decision = self.workflow_policy_service.decide_promotion(
                finding=finding,
                policy_state=policy_state,
            )
            if decision.disposition != "promote":
                backlog_only_count += 1
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
        return GitHubFindingSyncResult(
            promoted_count=promoted_count,
            backlog_only_count=backlog_only_count,
            created_count=created_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
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
