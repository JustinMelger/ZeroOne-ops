from zeroone_ops.models.dashboard import (
    DashboardPolicyState,
    DashboardSeverityPolicyStateEntry,
)
from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import ChangeRequestRef
from zeroone_ops.services.control_plane.work_items.github_finding_sync_service import (
    GitHubFindingSyncService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_parser import (
    GitHubWorkItemParser,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_renderer import (
    GitHubWorkItemRenderer,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)


class FakeGitHubWorkItemClient:
    def __init__(self) -> None:
        self.issues: list[GitHubIssueInfo] = []
        self.closed_issues: list[GitHubIssueInfo] = []

    def list_open_issues(
        self,
        *,
        repository_id: str,
        labels: list[str] | None = None,
    ) -> list[GitHubIssueInfo]:
        del repository_id, labels
        return list(self.issues)

    def list_closed_issues(
        self,
        *,
        repository_id: str,
        labels: list[str] | None = None,
    ) -> list[GitHubIssueInfo]:
        del repository_id, labels
        return list(self.closed_issues)

    def create_issue(
        self,
        *,
        repository_id: str,
        title: str,
        body: str,
        labels: list[str],
    ) -> GitHubIssueInfo:
        del repository_id, labels
        issue = GitHubIssueInfo(
            id=len(self.issues) + 1,
            number=len(self.issues) + 1,
            web_url=f"https://github.example.com/octo-org/octo-repo/issues/{len(self.issues) + 1}",
            title=title,
            body=body,
        )
        self.issues.append(issue)
        return issue

    def close_issue(self, *, repository_id: str, issue_number: int) -> GitHubIssueInfo:
        del repository_id
        issue = next(issue for issue in self.issues if issue.number == issue_number)
        self.issues = [item for item in self.issues if item.number != issue_number]
        self.closed_issues.append(issue)
        return issue

    def reopen_issue(self, *, repository_id: str, issue_number: int) -> GitHubIssueInfo:
        del repository_id
        issue = next(issue for issue in self.closed_issues if issue.number == issue_number)
        self.closed_issues = [item for item in self.closed_issues if item.number != issue_number]
        self.issues.append(issue)
        return issue

    def update_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
        title: str,
        body: str,
        labels: list[str],
    ) -> GitHubIssueInfo:
        del repository_id, labels
        issue = GitHubIssueInfo(
            id=issue_number,
            number=issue_number,
            web_url=f"https://github.example.com/octo-org/octo-repo/issues/{issue_number}",
            title=title,
            body=body,
        )
        self.issues = [
            issue if existing.number == issue_number else existing for existing in self.issues
        ]
        self.closed_issues = [
            issue if existing.number == issue_number else existing
            for existing in self.closed_issues
        ]
        return issue


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
            validation_commands=["uv run ruff check src/service.py"],
            expected_change="Use direct truthiness.",
            constraints="Keep the expression side-effect free.",
            acceptance_criteria=["The E712 finding is resolved."],
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


def test_sync_creates_work_item_for_policy_promoted_finding() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )

    result = service.sync(
        repository_id="octo-org/octo-repo",
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )

    assert result.promoted_count == 1
    assert result.created_count == 1
    assert result.backlog_only_count == 0
    assert result.normalized_severity_counts == {"medium": 1}
    assert result.enabled_severities == ("high", "medium")
    assert result.backlog_reason_counts == {}
    assert len(client.issues) == 1
    assert client.issues[0].title == "ZeroOne Ops: E712 in service.py:12"
    assert "Use direct truthiness instead of == True." in client.issues[0].body
    assert '"category": "static_analysis_fix"' in client.issues[0].body
    assert "- Rule: `E712`" in client.issues[0].body
    parsed = GitHubWorkItemParser().parse_work_item_state(client.issues[0].body)
    assert parsed is not None
    assert parsed.remediation_context.validation_commands == ["uv run ruff check src/service.py"]
    assert parsed.remediation_context.expected_change == "Use direct truthiness."


def test_sync_keeps_disabled_severity_as_backlog_only() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )

    result = service.sync(
        repository_id="octo-org/octo-repo",
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )

    assert result.promoted_count == 0
    assert result.backlog_only_count == 1
    assert result.normalized_severity_counts == {"medium": 1}
    assert result.enabled_severities == ("high",)
    assert result.backlog_reason_counts == {"severity_disabled": 1}
    assert client.issues == []


def test_sync_dry_run_counts_promoted_findings_without_creating_issues() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )

    result = service.sync(
        repository_id="octo-org/octo-repo",
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
        persist=False,
    )

    assert result.promoted_count == 1
    assert result.created_count == 0
    assert client.issues == []


def test_sync_defers_eligible_findings_when_active_capacity_is_full() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"
    policy_state = _policy_state(medium_enabled=True)

    service.sync(
        repository_id=repository_id,
        findings=[_finding(finding_id="existing", severity="high")],
        policy_state=policy_state,
        max_active_work_items=1,
    )
    result = service.sync(
        repository_id=repository_id,
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
    assert len(client.issues) == 1


def test_sync_uses_source_priority_before_severity_for_capacity() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )

    result = service.sync(
        repository_id="octo-org/octo-repo",
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
    work_item = GitHubWorkItemParser().parse_work_item_state(client.issues[0].body)
    assert work_item is not None
    assert work_item.source.source == "semgrep-sarif"


def test_sync_closes_existing_work_outside_capacity_and_reopens_it_when_capacity_frees() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"
    policy_state = _policy_state(medium_enabled=True)
    findings = [
        _finding(finding_id="high", severity="high"),
        _finding(finding_id="medium", severity="medium"),
    ]

    service.sync(
        repository_id=repository_id,
        findings=findings,
        policy_state=policy_state,
        max_active_work_items=2,
    )
    medium_issue = next(issue for issue in client.issues if "medium" in issue.body)
    medium_work_item = GitHubWorkItemParser().parse_work_item_state(medium_issue.body)
    assert medium_work_item is not None
    client.issues = [
        issue.model_copy(
            update={
                "body": GitHubWorkItemRenderer().render_body(
                    medium_work_item.model_copy(update={"status": "candidate"})
                )
            }
        )
        if issue.number == medium_issue.number
        else issue
        for issue in client.issues
    ]
    deferred_result = service.sync(
        repository_id=repository_id,
        findings=findings,
        policy_state=policy_state,
        max_active_work_items=1,
    )

    deferred = GitHubWorkItemParser().parse_work_item_state(client.closed_issues[0].body)

    assert deferred_result.capacity_deferred_count == 1
    assert deferred is not None
    assert deferred.status == "capacity_deferred"
    assert deferred.capacity_deferral is not None

    client.issues = []
    reactivated_result = service.sync(
        repository_id=repository_id,
        findings=[findings[1]],
        policy_state=policy_state,
        max_active_work_items=1,
    )

    assert reactivated_result.policy_reactivated_count == 1
    assert len(client.issues) == 1
    reopened = GitHubWorkItemParser().parse_work_item_state(client.issues[0].body)
    assert reopened is not None
    assert reopened.status == "approved"
    assert reopened.capacity_deferral is None


def test_sync_dry_run_does_not_load_or_write_work_items() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"
    policy_state = _policy_state(medium_enabled=True)
    result = service.sync(
        repository_id=repository_id,
        findings=[_finding(finding_id="candidate", severity="high")],
        policy_state=policy_state,
        max_active_work_items=1,
        persist=False,
    )

    assert result.promoted_count == 1
    assert client.issues == []


def test_sync_skips_duplicate_open_authoritative_identities(monkeypatch) -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"
    policy_state = _policy_state(medium_enabled=True)
    finding = _finding(finding_id="duplicate", severity="high")
    service.sync(
        repository_id=repository_id,
        findings=[finding],
        policy_state=policy_state,
    )
    original = client.issues[0]
    client.issues.append(
        original.model_copy(
            update={
                "id": 2,
                "number": 2,
                "web_url": "https://github.example.com/octo-org/octo-repo/issues/2",
            }
        )
    )

    def fail_provider_write(**kwargs):
        del kwargs
        raise AssertionError("Ambiguous identities must not be written.")

    monkeypatch.setattr(service.work_item_service, "upsert_work_item", fail_provider_write)
    monkeypatch.setattr(service.work_item_service, "update_existing_work_item", fail_provider_write)

    result = service.sync(
        repository_id=repository_id,
        findings=[finding],
        policy_state=policy_state,
    )

    assert result.promoted_count == 0
    assert result.backlog_only_count == 1
    assert result.backlog_reason_counts == {"work_item_identity_ambiguous": 1}


def test_sync_reuses_existing_authoritative_work_item() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    policy_state = _policy_state(medium_enabled=True)

    service.sync(
        repository_id="octo-org/octo-repo",
        findings=[_finding()],
        policy_state=policy_state,
    )
    result = service.sync(
        repository_id="octo-org/octo-repo",
        findings=[_finding()],
        policy_state=policy_state,
    )

    assert result.promoted_count == 1
    assert result.unchanged_count == 1
    assert len(client.issues) == 1


def test_sync_defers_unlinked_approved_work_item_when_severity_is_disabled() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )
    result = service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )

    parsed = GitHubWorkItemParser().parse_work_item_state(client.closed_issues[0].body)

    assert result.backlog_only_count == 1
    assert result.policy_deferred_count == 1
    assert result.retained_protected_count == 0
    assert result.updated_count == 1
    assert parsed is not None
    assert parsed.status == "policy_deferred"
    assert parsed.policy_deferral is not None


def test_sync_completes_stale_work_item_when_its_severity_is_disabled() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding(finding_id="mypy:no-untyped-def:1080", severity="high")],
        policy_state=_policy_state(medium_enabled=False),
    )
    result = service.sync(
        repository_id=repository_id,
        findings=[],
        managed_source_ids={"ruff"},
        policy_state=_policy_state(medium_enabled=False, high_enabled=False),
        run_id="complete-missing-high",
    )

    parsed = GitHubWorkItemParser().parse_work_item_state(client.closed_issues[0].body)

    assert result.no_longer_detected_count == 1
    assert result.policy_deferred_count == 0
    assert result.stale_demoted_to_candidate_count == 0
    assert parsed is not None
    assert parsed.status == "completed"
    assert parsed.resolution == "no_longer_detected"
    assert parsed.policy_deferral is None


def test_sync_reopens_policy_deferred_work_item_when_severity_is_enabled() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )
    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )
    result = service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )

    parsed = GitHubWorkItemParser().parse_work_item_state(client.issues[0].body)

    assert result.promoted_count == 1
    assert result.policy_reactivated_count == 1
    assert result.updated_count == 1
    assert len(client.issues) == 1
    assert parsed is not None
    assert parsed.status == "approved"


def test_sync_skips_ambiguous_closed_policy_deferred_work_items() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )
    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )
    original = client.closed_issues[0]
    client.closed_issues.append(
        original.model_copy(update={"id": 2, "number": 2, "web_url": "https://example.com/2"})
    )

    result = service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )

    assert result.promoted_count == 0
    assert result.backlog_only_count == 1
    assert result.backlog_reason_counts == {"work_item_identity_ambiguous": 1}
    assert client.issues == []


def test_sync_keeps_in_progress_work_item_when_severity_is_disabled() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )
    parser = GitHubWorkItemParser()
    rendered = parser.parse_work_item_state(client.issues[0].body)
    assert rendered is not None
    client.issues[0] = client.issues[0].model_copy(
        update={
            "body": GitHubWorkItemRenderer().render_body(
                rendered.model_copy(update={"status": "in_progress"})
            )
        }
    )

    result = service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )

    parsed = parser.parse_work_item_state(client.issues[0].body)

    assert result.demoted_to_candidate_count == 0
    assert result.retained_protected_count == 1
    assert result.updated_count == 0
    assert parsed is not None
    assert parsed.status == "in_progress"


def test_sync_preserves_blocked_work_item_when_active_finding_remains_promoted() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )
    parser = GitHubWorkItemParser()
    rendered = parser.parse_work_item_state(client.issues[0].body)
    assert rendered is not None
    client.issues[0] = client.issues[0].model_copy(
        update={
            "body": GitHubWorkItemRenderer().render_body(
                rendered.model_copy(update={"status": "blocked"})
            )
        }
    )

    result = service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )

    parsed = parser.parse_work_item_state(client.issues[0].body)

    assert result.promoted_count == 1
    assert parsed is not None
    assert parsed.status == "blocked"


def test_sync_preserves_dismissed_work_item_when_active_finding_remains_promoted() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )
    parser = GitHubWorkItemParser()
    rendered = parser.parse_work_item_state(client.issues[0].body)
    assert rendered is not None
    client.issues[0] = client.issues[0].model_copy(
        update={
            "body": GitHubWorkItemRenderer().render_body(
                rendered.model_copy(update={"status": "dismissed"})
            )
        }
    )

    result = service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )

    parsed = parser.parse_work_item_state(client.issues[0].body)

    assert result.promoted_count == 1
    assert parsed is not None
    assert parsed.status == "dismissed"


def test_sync_keeps_linked_work_item_when_severity_is_disabled() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )
    parser = GitHubWorkItemParser()
    rendered = parser.parse_work_item_state(client.issues[0].body)
    assert rendered is not None
    client.issues[0] = client.issues[0].model_copy(
        update={
            "body": GitHubWorkItemRenderer().render_body(
                rendered.model_copy(
                    update={
                        "linked_change_request": ChangeRequestRef(
                            number=42,
                            web_url="https://github.example.com/octo-org/octo-repo/pull/42",
                        )
                    }
                )
            )
        }
    )

    result = service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=False),
    )

    parsed = parser.parse_work_item_state(client.issues[0].body)

    assert result.demoted_to_candidate_count == 0
    assert result.retained_protected_count == 1
    assert result.updated_count == 0
    assert parsed is not None
    assert parsed.status == "approved"
    assert parsed.linked_change_request is not None
    assert parsed.linked_change_request.number == 42


def test_sync_completes_stale_work_item_from_complete_managed_source() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )
    result = service.sync(
        repository_id=repository_id,
        findings=[],
        policy_state=_policy_state(medium_enabled=True),
        managed_source_ids={"ruff"},
    )

    parsed = GitHubWorkItemParser().parse_work_item_state(client.closed_issues[0].body)

    assert result.stale_demoted_to_candidate_count == 0
    assert result.stale_retained_protected_count == 0
    assert result.no_longer_detected_count == 1
    assert result.updated_count == 1
    assert parsed is not None
    assert parsed.status == "completed"
    assert parsed.resolution == "no_longer_detected"


def test_sync_does_not_reconcile_stale_items_without_managed_source_ownership() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )
    result = service.sync(
        repository_id=repository_id,
        findings=[],
        policy_state=_policy_state(medium_enabled=True),
        managed_source_ids=set(),
    )

    parsed = GitHubWorkItemParser().parse_work_item_state(client.issues[0].body)

    assert result.stale_demoted_to_candidate_count == 0
    assert result.stale_retained_protected_count == 0
    assert result.updated_count == 0
    assert parsed is not None
    assert parsed.status == "approved"


def test_sync_keeps_in_progress_stale_work_item() -> None:
    client = FakeGitHubWorkItemClient()
    service = GitHubFindingSyncService(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
    )
    repository_id = "octo-org/octo-repo"

    service.sync(
        repository_id=repository_id,
        findings=[_finding()],
        policy_state=_policy_state(medium_enabled=True),
    )
    parser = GitHubWorkItemParser()
    rendered = parser.parse_work_item_state(client.issues[0].body)
    assert rendered is not None
    client.issues[0] = client.issues[0].model_copy(
        update={
            "body": GitHubWorkItemRenderer().render_body(
                rendered.model_copy(update={"status": "in_progress"})
            )
        }
    )

    result = service.sync(
        repository_id=repository_id,
        findings=[],
        policy_state=_policy_state(medium_enabled=True),
        managed_source_ids={"ruff"},
    )

    parsed = parser.parse_work_item_state(client.issues[0].body)

    assert result.stale_demoted_to_candidate_count == 0
    assert result.stale_retained_protected_count == 1
    assert result.updated_count == 0
    assert parsed is not None
    assert parsed.status == "in_progress"
