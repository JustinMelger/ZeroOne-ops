from ai_sonar_bot.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    DashboardSection,
    empty_sections,
)
from ai_sonar_bot.services.dashboard_reconciliation_intake import (
    DashboardReconciliationIntakeService,
)


def build_item(
    *,
    item_id: str,
    status: str = "mr_opened",
    merge_request_url: str | None = "https://gitlab.example.com/group/project/-/merge_requests/1",
    branch_name: str | None = "zeroone-ops/issue-1/service",
    commit_sha: str | None = "abc123",
) -> DashboardItem:
    return DashboardItem(
        id=item_id,
        source="sonarqube",
        type="code_smell_fix",
        status=status,
        title="Fix issue",
        summary="Fix the issue safely.",
        priority="low",
        source_reference="issue-1",
        file="src/service.py",
        line=10,
        rule="python:S1125",
        severity="LOW",
        merge_request_url=merge_request_url,
        branch_name=branch_name,
        commit_sha=commit_sha,
    )


def build_document(*, items: list[DashboardItem]) -> DashboardDocument:
    sections = empty_sections()
    sections[2] = DashboardSection(
        key="merge_requests_opened",
        title="Merge Requests Opened",
        items=items,
    )
    return DashboardDocument(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        sections=sections,
    )


class FakeDashboardService:
    def __init__(self, document: DashboardDocument) -> None:
        self.document = document

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        del project_id
        return self.document


def test_select_item_returns_reconciliation_ready_dashboard_items() -> None:
    service = DashboardReconciliationIntakeService(
        dashboard_service=FakeDashboardService(
            build_document(items=[build_item(item_id="sonar:1"), build_item(item_id="sonar:2")])
        )
    )

    result = service.select_item(project_id="123")

    assert result.selected_item is not None
    assert result.selected_item.id == "sonar:1"
    assert [item.id for item in result.selected_items] == ["sonar:1", "sonar:2"]
    assert result.item_count == 2
    assert result.message == ""


def test_select_item_skips_items_without_required_traceability() -> None:
    service = DashboardReconciliationIntakeService(
        dashboard_service=FakeDashboardService(
            build_document(
                items=[
                    build_item(item_id="sonar:1", merge_request_url=None),
                    build_item(item_id="sonar:2", branch_name=None),
                    build_item(item_id="sonar:3"),
                ]
            )
        )
    )

    result = service.select_item(project_id="123")

    assert result.selected_item is not None
    assert result.selected_item.id == "sonar:3"
    assert [item.id for item in result.selected_items] == ["sonar:3"]


def test_select_item_reports_skip_reasons_when_no_item_is_eligible() -> None:
    service = DashboardReconciliationIntakeService(
        dashboard_service=FakeDashboardService(
            build_document(
                items=[
                    build_item(item_id="sonar:1", status="open"),
                    build_item(item_id="sonar:2", commit_sha=None),
                ]
            )
        )
    )

    result = service.select_item(project_id="123")

    assert result.selected_item is None
    assert "No reconciliation-ready dashboard item found" in result.message
    assert "unsupported status" in result.message
    assert "stored commit SHA" in result.message
