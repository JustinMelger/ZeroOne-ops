from zeroone_ops.models.dashboard import (
    DashboardPolicyState,
    DashboardSeverityPolicyStateEntry,
)
from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service import (
    GitLabFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_upsert_service import (
    GitLabWorkItemUpsertResult,
)


class FakeGitLabWorkItemService:
    def __init__(self) -> None:
        self.work_items: dict[tuple[str, str, str | None, str], WorkItemState] = {}

    def upsert_work_item(
        self,
        *,
        project_id: str,
        work_item: WorkItemState,
    ) -> GitLabWorkItemUpsertResult:
        del project_id
        existing = self.work_items.get(work_item.identity_key)
        if existing is None:
            self.work_items[work_item.identity_key] = work_item
            return GitLabWorkItemUpsertResult(
                issue=_issue(work_item),
                action="created",
                work_item=work_item,
            )
        if existing == work_item:
            return GitLabWorkItemUpsertResult(
                issue=_issue(existing),
                action="unchanged",
                work_item=existing,
            )
        self.work_items[work_item.identity_key] = work_item
        return GitLabWorkItemUpsertResult(
            issue=_issue(work_item),
            action="updated",
            work_item=work_item,
        )

    def find_open_work_item_by_source(
        self,
        *,
        project_id: str,
        kind: str,
        source: WorkItemSourceRef,
    ) -> GitLabWorkItemLookupResult | None:
        del project_id
        identity_key = (
            source.source,
            source.source_item_key,
            source.repository_scope,
            kind,
        )
        work_item = self.work_items.get(identity_key)
        return _lookup(work_item) if work_item is not None else None

    def list_open_work_items(self, *, project_id: str) -> list[GitLabWorkItemLookupResult]:
        return [
            _lookup(work_item)
            for work_item in self.work_items.values()
            if work_item.source.repository_scope == project_id
        ]


def _issue(work_item: WorkItemState) -> GitLabIssueInfo:
    return GitLabIssueInfo(
        id=1,
        iid=1,
        web_url="https://gitlab.example.com/group/project/-/issues/1",
        title=work_item.summary,
        description="",
    )


def _lookup(work_item: WorkItemState) -> GitLabWorkItemLookupResult:
    return GitLabWorkItemLookupResult(issue=_issue(work_item), work_item=work_item)


def _finding(
    *,
    finding_id: str = "ruff:E712:service",
    severity: str = "medium",
) -> NormalizedFinding:
    return NormalizedFinding(
        finding_id=finding_id,
        source_id="ruff",
        severity=severity,  # type: ignore[arg-type]
        title="Avoid equality comparisons to True",
        summary="Use direct truthiness instead of == True.",
        repository_path="src/service.py",
        line_start=12,
        remediation_context=RemediationContext(
            category="static_analysis_fix",
            diagnostic_code="E712",
        ),
    )


def _policy_state(*, medium_enabled: bool) -> DashboardPolicyState:
    return DashboardPolicyState(
        severity_policy=[
            DashboardSeverityPolicyStateEntry(severity="low", enabled=False),
            DashboardSeverityPolicyStateEntry(severity="medium", enabled=medium_enabled),
            DashboardSeverityPolicyStateEntry(severity="high", enabled=True),
        ]
    )


def test_sync_creates_gitlab_work_item_for_policy_promoted_finding() -> None:
    work_item_service = FakeGitLabWorkItemService()
    service = GitLabFindingSyncService(
        work_item_service=work_item_service,  # type: ignore[arg-type]
    )

    result = service.sync(
        project_id="group/project",
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )

    assert result.promoted_count == 1
    assert result.created_count == 1
    assert result.backlog_only_count == 0
    assert result.enabled_severities == ("high", "medium")
    work_item = next(iter(work_item_service.work_items.values()))
    assert work_item.source.repository_scope == "group/project"
    assert work_item.status == "approved"
    assert work_item.remediation_context.category == "static_analysis_fix"


def test_sync_keeps_disabled_severity_backlog_only_without_creating_work_item() -> None:
    work_item_service = FakeGitLabWorkItemService()
    service = GitLabFindingSyncService(
        work_item_service=work_item_service,  # type: ignore[arg-type]
    )

    result = service.sync(
        project_id="group/project",
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )

    assert result.promoted_count == 0
    assert result.backlog_only_count == 1
    assert result.backlog_reason_counts == {"severity_disabled": 1}
    assert work_item_service.work_items == {}


def test_sync_demotes_stale_unlinked_approved_work_item_from_managed_source() -> None:
    work_item_service = FakeGitLabWorkItemService()
    service = GitLabFindingSyncService(
        work_item_service=work_item_service,  # type: ignore[arg-type]
    )
    project_id = "group/project"
    service.sync(
        project_id=project_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )

    result = service.sync(
        project_id=project_id,
        findings=[],
        policy_state=_policy_state(medium_enabled=True),
        managed_source_ids={"ruff"},
    )

    assert result.stale_demoted_to_candidate_count == 1
    assert next(iter(work_item_service.work_items.values())).status == "candidate"
