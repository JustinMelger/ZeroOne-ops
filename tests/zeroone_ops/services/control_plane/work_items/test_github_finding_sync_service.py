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

    def list_open_issues(
        self,
        *,
        repository_id: str,
        labels: list[str] | None = None,
    ) -> list[GitHubIssueInfo]:
        del repository_id, labels
        return list(self.issues)

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
        return issue


def _finding(*, severity: str = "medium") -> NormalizedFinding:
    return NormalizedFinding(
        finding_id="ruff:E712:service",
        source_id="ruff",
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


def _policy_state(*, medium_enabled: bool) -> DashboardPolicyState:
    return DashboardPolicyState(
        severity_policy=[
            DashboardSeverityPolicyStateEntry(severity="low", enabled=False),
            DashboardSeverityPolicyStateEntry(severity="medium", enabled=medium_enabled),
            DashboardSeverityPolicyStateEntry(severity="high", enabled=True),
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
    assert client.issues[0].title == "ZeroOne Ops: E712: Avoid equality comparisons to True"
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


def test_sync_demotes_unlinked_approved_work_item_when_severity_is_disabled() -> None:
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

    parsed = GitHubWorkItemParser().parse_work_item_state(client.issues[0].body)

    assert result.backlog_only_count == 1
    assert result.demoted_to_candidate_count == 1
    assert result.retained_protected_count == 0
    assert result.updated_count == 1
    assert parsed is not None
    assert parsed.status == "candidate"


def test_sync_repromotes_candidate_work_item_when_severity_is_enabled() -> None:
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
    assert result.updated_count == 1
    assert len(client.issues) == 1
    assert parsed is not None
    assert parsed.status == "approved"


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


def test_sync_demotes_stale_work_item_from_complete_managed_source() -> None:
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

    parsed = GitHubWorkItemParser().parse_work_item_state(client.issues[0].body)

    assert result.stale_demoted_to_candidate_count == 1
    assert result.stale_retained_protected_count == 0
    assert result.updated_count == 1
    assert parsed is not None
    assert parsed.status == "candidate"


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
