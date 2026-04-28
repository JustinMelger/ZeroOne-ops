from zeroone_ops.models.dashboard import (
    DashboardIssueClassInventoryEntry,
    DashboardItem,
    DashboardPolicyState,
    DashboardPolicyView,
    DashboardSeverityPolicyEntry,
)
from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.services.dashboard.dashboard_service import DashboardService


def build_item(
    *,
    item_id: str,
    status: str = "open",
    item_type: str = "code_smell_fix",
    priority: str = "low",
) -> DashboardItem:
    return DashboardItem(
        id=item_id,
        source="sonarqube" if item_type != "review_status" else "pull_request_review",
        type=item_type,
        status=status,
        title="Title",
        summary="Summary",
        priority=priority,
        source_reference="ref-1",
    )


class FakeDashboardClient:
    def __init__(self, existing_issue: GitLabIssueInfo | None = None) -> None:
        self.existing_issue = existing_issue
        self.created_issue: GitLabIssueInfo | None = None
        self.updated_issue: GitLabIssueInfo | None = None
        self.notes: list[GitLabIssueNote] = []

    def find_open_issue(
        self,
        *,
        project_id: str,
        title: str,
        labels: list[str] | None = None,
    ) -> GitLabIssueInfo | None:
        del project_id, title, labels
        return self.existing_issue

    def create_issue(
        self,
        *,
        project_id: str,
        title: str,
        description: str,
        labels: list[str] | None = None,
    ) -> GitLabIssueInfo:
        del project_id, labels
        self.created_issue = GitLabIssueInfo(
            id=10,
            iid=11,
            web_url="https://gitlab.example.com/group/project/-/issues/11",
            title=title,
            description=description,
        )
        self.existing_issue = self.created_issue
        return self.created_issue

    def update_issue(self, *, project_id: str, issue_iid: int, description: str) -> GitLabIssueInfo:
        del project_id, issue_iid
        assert self.existing_issue is not None
        self.updated_issue = GitLabIssueInfo(
            id=self.existing_issue.id,
            iid=self.existing_issue.iid,
            web_url=self.existing_issue.web_url,
            title=self.existing_issue.title,
            description=description,
        )
        self.existing_issue = self.updated_issue
        return self.updated_issue

    def list_issue_notes(self, *, project_id: str, issue_iid: int) -> list[GitLabIssueNote]:
        del project_id, issue_iid
        return list(self.notes)


def test_load_or_create_creates_dashboard_when_missing() -> None:
    service = DashboardService(FakeDashboardClient())

    document = service.load_or_create(project_id="123")

    assert document.title == "AI Code Ops Work Queue"
    assert len(document.sections) == 7
    assert document.sections[0].items == []


def test_upsert_items_updates_existing_dashboard_without_duplicates() -> None:
    existing_issue = GitLabIssueInfo(
        id=10,
        iid=11,
        web_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        description="",
    )
    client = FakeDashboardClient(existing_issue=existing_issue)
    service = DashboardService(client)

    initial = service.upsert_items(project_id="123", items=[build_item(item_id="sonar:1")])
    updated = service.upsert_items(
        project_id="123",
        items=[
            build_item(item_id="sonar:1", status="in_progress"),
            build_item(item_id="mr-review:42:abc123", status="done", item_type="review_status"),
        ],
    )

    assert len(initial.items_by_id()) == 1
    assert len(updated.items_by_id()) == 2
    assert updated.items_by_id()["sonar:1"].status == "in_progress"
    assert updated.sections[1].items[0].id == "sonar:1"
    assert updated.sections[4].items[0].id == "mr-review:42:abc123"


def test_upsert_items_applies_section_retention_limits() -> None:
    existing_issue = GitLabIssueInfo(
        id=10,
        iid=11,
        web_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        description="",
    )
    client = FakeDashboardClient(existing_issue=existing_issue)
    service = DashboardService(
        client,
        section_item_limits={
            "open_candidates": 2,
            "in_progress": 25,
            "merge_requests_opened": 25,
            "completed": 25,
            "merge_request_reviews": 25,
            "rejected_or_ignored": 25,
            "recent_failures": 25,
        },
    )

    updated = service.upsert_items(
        project_id="123",
        items=[
            build_item(item_id="sonar:low", priority="low"),
            build_item(item_id="sonar:medium", priority="medium"),
            build_item(item_id="sonar:high", priority="high"),
        ],
    )

    open_items = updated.sections[0].items
    assert len(open_items) == 2
    assert [item.id for item in open_items] == ["sonar:high", "sonar:medium"]


def test_done_items_render_under_completed_section() -> None:
    existing_issue = GitLabIssueInfo(
        id=10,
        iid=11,
        web_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        description="",
    )
    client = FakeDashboardClient(existing_issue=existing_issue)
    service = DashboardService(client)

    updated = service.upsert_items(
        project_id="123",
        items=[build_item(item_id="sonar:done", status="done")],
    )

    assert updated.sections[3].items[0].id == "sonar:done"
    assert updated.sections[3].items[0].status == "done"


class FakePolicyViewBuilder:
    def resolve_policy_state(
        self,
        policy_state: DashboardPolicyState | None,
    ) -> DashboardPolicyState:
        return policy_state or DashboardPolicyState()

    def build(
        self,
        items: list[DashboardItem],
        *,
        policy_state: DashboardPolicyState | None = None,
    ) -> DashboardPolicyView:
        del policy_state
        return DashboardPolicyView(
            severity_policy=[
                DashboardSeverityPolicyEntry(
                    severity="low",
                    enabled=True,
                )
            ],
            issue_class_inventory=[
                DashboardIssueClassInventoryEntry(
                    source="sonarqube",
                    issue_key="python:S1125",
                    matching_items_count=len(items),
                    severities_present=["low"],
                    automation_status="eligible for automation",
                )
            ],
        )


def test_load_or_create_migrates_legacy_dashboard_to_current_schema() -> None:
    legacy_body = (
        "Machine-managed remediation and review items for this repository.\n\n"
        "## Open Candidates\n\n"
        "### Overview\n\n"
        "| Open | In progress | MR opened | Failed | Done |\n"
        "|---|---|---|---|---|\n"
        "| 0 | 0 | 0 | 0 | 0 |\n\n"
        "### Needs Attention\n\n"
        "No items.\n\n"
        "### In Flight\n\n"
        "No items.\n\n"
        "### Completed\n\n"
        "No items.\n\n"
        "### Work Type Breakdown\n\n"
        "No items.\n"
    )
    existing_issue = GitLabIssueInfo(
        id=10,
        iid=11,
        web_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        description=legacy_body,
    )
    client = FakeDashboardClient(existing_issue=existing_issue)
    service = DashboardService(
        client,
        policy_view_builder=FakePolicyViewBuilder(),
    )

    document = service.load_or_create(project_id="123")

    assert document.schema_version == 1
    assert client.updated_issue is not None
    assert "<!-- zeroone-ops:dashboard-schema:v1 -->" in client.updated_issue.description
    assert "## Automation Severity Policy" in client.updated_issue.description


def test_load_or_create_replays_severity_policy_actions_from_issue_notes() -> None:
    existing_issue = GitLabIssueInfo(
        id=10,
        iid=11,
        web_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        description="",
    )
    client = FakeDashboardClient(existing_issue=existing_issue)
    client.notes = [
        GitLabIssueNote(
            id=12,
            body="/zeroone policy severity disable high",
            author_username="operator",
            created_at="2026-04-28T10:00:00.000Z",
        )
    ]
    service = DashboardService(
        client,
        policy_view_builder=FakePolicyViewBuilder(),
    )

    document = service.load_or_create(project_id="123")

    severity_by_name = {entry.severity: entry for entry in document.policy_state.severity_policy}
    assert severity_by_name["high"].enabled is False
    assert severity_by_name["high"].updated_by == "operator"
    assert severity_by_name["high"].note_id == 12
