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
        self.listed_work_items: list[GitLabWorkItemLookupResult] | None = None
        self.closed_deferred_work_items: list[GitLabWorkItemLookupResult] | None = None
        self.update_existing_calls = 0
        self.closed_issue_iids: list[int] = []
        self.reopened_issue_iids: list[int] = []

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

    def update_existing_work_item(
        self,
        *,
        project_id: str,
        existing: GitLabWorkItemLookupResult,
        work_item: WorkItemState,
    ) -> GitLabWorkItemUpsertResult:
        del project_id
        self.update_existing_calls += 1
        if existing.work_item == work_item:
            return GitLabWorkItemUpsertResult(
                issue=existing.issue,
                action="unchanged",
                work_item=work_item,
            )
        self.work_items[work_item.identity_key] = work_item
        return GitLabWorkItemUpsertResult(
            issue=_issue(work_item),
            action="updated",
            work_item=work_item,
        )

    def list_open_work_items(self, *, project_id: str) -> list[GitLabWorkItemLookupResult]:
        if self.listed_work_items is not None:
            return self.listed_work_items
        return [
            _lookup(work_item)
            for work_item in self.work_items.values()
            if work_item.source.repository_scope == project_id
            and work_item.status not in {"policy_deferred", "capacity_deferred"}
        ]

    def list_closed_policy_deferred_work_items(
        self, *, project_id: str
    ) -> list[GitLabWorkItemLookupResult]:
        if self.closed_deferred_work_items is not None:
            return self.closed_deferred_work_items
        return [
            _lookup(work_item)
            for work_item in self.work_items.values()
            if work_item.source.repository_scope == project_id
            and work_item.status == "policy_deferred"
        ]

    def list_closed_capacity_deferred_work_items(
        self, *, project_id: str
    ) -> list[GitLabWorkItemLookupResult]:
        return [
            _lookup(work_item)
            for work_item in self.work_items.values()
            if work_item.source.repository_scope == project_id
            and work_item.status == "capacity_deferred"
        ]

    def close_work_item_issue(self, *, project_id: str, issue_iid: int) -> None:
        del project_id
        self.closed_issue_iids.append(issue_iid)

    def reopen_work_item_issue(self, *, project_id: str, issue_iid: int) -> None:
        del project_id
        self.reopened_issue_iids.append(issue_iid)


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
    source_id: str = "ruff",
) -> NormalizedFinding:
    return NormalizedFinding(
        finding_id=finding_id,
        source_id=source_id,
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


def _policy_state(
    *,
    medium_enabled: bool,
    high_enabled: bool = True,
) -> DashboardPolicyState:
    return DashboardPolicyState(
        severity_policy=[
            DashboardSeverityPolicyStateEntry(severity="low", enabled=False),
            DashboardSeverityPolicyStateEntry(severity="medium", enabled=medium_enabled),
            DashboardSeverityPolicyStateEntry(severity="high", enabled=high_enabled),
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


def test_sync_defers_eligible_findings_when_active_capacity_is_full() -> None:
    work_item_service = FakeGitLabWorkItemService()
    service = GitLabFindingSyncService(
        work_item_service=work_item_service,  # type: ignore[arg-type]
    )
    project_id = "group/project"
    policy_state = _policy_state(medium_enabled=True)

    service.sync(
        project_id=project_id,
        findings=[_finding(finding_id="existing", severity="high")],
        policy_state=policy_state,
        max_active_work_items=1,
    )
    result = service.sync(
        project_id=project_id,
        findings=[
            _finding(finding_id="existing", severity="high"),
            _finding(finding_id="deferred", severity="high"),
        ],
        policy_state=policy_state,
        max_active_work_items=1,
    )

    assert result.promoted_count == 1
    assert result.backlog_only_count == 1
    assert result.backlog_reason_counts == {"promotion_capacity_exhausted": 1}
    assert len(work_item_service.work_items) == 1


def test_sync_uses_source_priority_before_severity_for_capacity() -> None:
    work_item_service = FakeGitLabWorkItemService()
    service = GitLabFindingSyncService(
        work_item_service=work_item_service,  # type: ignore[arg-type]
    )

    result = service.sync(
        project_id="group/project",
        findings=[
            _finding(finding_id="ruff-high", severity="high", source_id="ruff-sarif"),
            _finding(
                finding_id="semgrep-medium",
                severity="medium",
                source_id="semgrep-sarif",
            ),
        ],
        policy_state=_policy_state(medium_enabled=True),
        max_active_work_items=1,
        source_priorities={"semgrep-sarif": 20, "ruff-sarif": 100},
    )

    assert result.promoted_count == 1
    assert result.backlog_reason_counts == {"promotion_capacity_exhausted": 1}
    work_item = next(iter(work_item_service.work_items.values()))
    assert work_item.source.source == "semgrep-sarif"


def test_sync_closes_existing_work_outside_capacity_and_reopens_it_when_capacity_frees() -> None:
    work_item_service = FakeGitLabWorkItemService()
    service = GitLabFindingSyncService(
        work_item_service=work_item_service,  # type: ignore[arg-type]
    )
    project_id = "group/project"
    policy_state = _policy_state(medium_enabled=True)
    findings = [
        _finding(finding_id="high", severity="high"),
        _finding(finding_id="medium", severity="medium"),
    ]

    service.sync(
        project_id=project_id,
        findings=findings,
        policy_state=policy_state,
        max_active_work_items=2,
    )
    medium_key = ("ruff", "medium", project_id, "remediation")
    work_item_service.work_items[medium_key] = work_item_service.work_items[medium_key].model_copy(
        update={"status": "candidate"}
    )
    deferred_result = service.sync(
        project_id=project_id,
        findings=findings,
        policy_state=policy_state,
        max_active_work_items=1,
    )

    deferred = next(
        work_item
        for work_item in work_item_service.work_items.values()
        if work_item.status == "capacity_deferred"
    )
    assert deferred_result.capacity_deferred_count == 1
    assert deferred.capacity_deferral is not None

    del work_item_service.work_items[("ruff", "high", project_id, "remediation")]
    reactivated_result = service.sync(
        project_id=project_id,
        findings=[findings[1]],
        policy_state=policy_state,
        max_active_work_items=1,
    )

    assert reactivated_result.policy_reactivated_count == 1
    reopened = next(iter(work_item_service.work_items.values()))
    assert reopened.status == "approved"
    assert reopened.capacity_deferral is None


def test_sync_skips_duplicate_open_authoritative_identities() -> None:
    work_item_service = FakeGitLabWorkItemService()
    service = GitLabFindingSyncService(
        work_item_service=work_item_service,  # type: ignore[arg-type]
    )
    project_id = "group/project"
    policy_state = _policy_state(medium_enabled=True)
    finding = _finding(finding_id="duplicate", severity="high")
    service.sync(
        project_id=project_id,
        findings=[finding],
        policy_state=policy_state,
    )
    original = next(iter(work_item_service.work_items.values()))
    work_item_service.listed_work_items = [
        _lookup(original),
        _lookup(original.model_copy(update={"work_item_id": "work-duplicate-copy"})),
    ]
    work_item_service.update_existing_calls = 0

    result = service.sync(
        project_id=project_id,
        findings=[finding],
        policy_state=policy_state,
    )

    assert result.promoted_count == 0
    assert result.backlog_only_count == 1
    assert result.backlog_reason_counts == {"work_item_identity_ambiguous": 1}
    assert work_item_service.update_existing_calls == 0


def test_sync_skips_ambiguous_closed_policy_deferred_work_items() -> None:
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
    service.sync(
        project_id=project_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )
    original = next(iter(work_item_service.work_items.values()))
    work_item_service.closed_deferred_work_items = [
        _lookup(original),
        _lookup(original.model_copy(update={"work_item_id": "work-duplicate-copy"})),
    ]

    result = service.sync(
        project_id=project_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )

    assert result.promoted_count == 0
    assert result.backlog_only_count == 1
    assert result.backlog_reason_counts == {"work_item_identity_ambiguous": 1}
    assert next(iter(work_item_service.work_items.values())).status == "policy_deferred"


def test_sync_defers_unlinked_approved_work_item_when_severity_is_disabled() -> None:
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
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )

    work_item = next(iter(work_item_service.work_items.values()))

    assert result.policy_deferred_count == 1
    assert work_item.status == "policy_deferred"
    assert work_item.policy_deferral is not None
    assert work_item_service.closed_issue_iids == [1]


def test_sync_completes_stale_work_item_when_its_severity_is_disabled() -> None:
    work_item_service = FakeGitLabWorkItemService()
    service = GitLabFindingSyncService(
        work_item_service=work_item_service,  # type: ignore[arg-type]
    )
    project_id = "group/project"

    service.sync(
        project_id=project_id,
        findings=[_finding(finding_id="mypy:no-untyped-def:1080", severity="high")],
        policy_state=_policy_state(medium_enabled=False),
    )
    result = service.sync(
        project_id=project_id,
        findings=[],
        managed_source_ids={"ruff"},
        policy_state=_policy_state(medium_enabled=False, high_enabled=False),
        run_id="complete-missing-high",
    )

    work_item = next(iter(work_item_service.work_items.values()))

    assert result.no_longer_detected_count == 1
    assert result.policy_deferred_count == 0
    assert result.stale_demoted_to_candidate_count == 0
    assert work_item.status == "completed"
    assert work_item.resolution == "no_longer_detected"
    assert work_item.policy_deferral is None
    assert work_item_service.closed_issue_iids == [1]


def test_sync_reopens_policy_deferred_work_item_when_severity_is_enabled() -> None:
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
    service.sync(
        project_id=project_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )
    result = service.sync(
        project_id=project_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )

    work_item = next(iter(work_item_service.work_items.values()))

    assert result.policy_reactivated_count == 1
    assert work_item.status == "approved"
    assert work_item.policy_deferral is None
    assert work_item_service.reopened_issue_iids == [1]


def test_sync_completes_deferred_work_only_after_managed_source_drops_finding() -> None:
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
    service.sync(
        project_id=project_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )
    result = service.sync(
        project_id=project_id,
        findings=[],
        policy_state=_policy_state(medium_enabled=False),
        managed_source_ids={"ruff"},
    )

    work_item = next(iter(work_item_service.work_items.values()))

    assert result.no_longer_detected_count == 1
    assert work_item.status == "completed"
    assert work_item.resolution == "no_longer_detected"


def test_sync_completes_stale_unlinked_approved_work_item_from_managed_source() -> None:
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

    work_item = next(iter(work_item_service.work_items.values()))

    assert result.stale_demoted_to_candidate_count == 0
    assert result.no_longer_detected_count == 1
    assert work_item.status == "completed"
    assert work_item.resolution == "no_longer_detected"
