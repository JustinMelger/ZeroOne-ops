from zeroone_ops.models.dashboard import (
    DashboardPolicyState,
    DashboardSeverityPolicyStateEntry,
)
from zeroone_ops.models.finding import NormalizedFinding
from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.services.control_plane.work_items.github_finding_sync_service import (
    GitHubFindingSyncService,
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
        self.issues = [issue]
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
    assert client.issues[0].title == "ZeroOne Ops: Avoid equality comparisons to True"
    assert "Use direct truthiness instead of == True." in client.issues[0].body


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
