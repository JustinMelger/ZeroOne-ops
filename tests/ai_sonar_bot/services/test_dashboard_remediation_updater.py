from ai_sonar_bot.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    DashboardSection,
    empty_sections,
)
from ai_sonar_bot.services.dashboard_remediation_updater import DashboardRemediationUpdater


def build_item(
    *,
    item_id: str = "sonar:1",
    status: str = "open",
) -> DashboardItem:
    return DashboardItem(
        id=item_id,
        source="sonarqube",
        type="code_smell_fix",
        status=status,
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        validation_commands=["uv run pytest"],
        constraints="Single-file only.",
    )


class FakeDashboardService:
    def __init__(self, document: DashboardDocument) -> None:
        self.document = document
        self.items: list[DashboardItem] = []
        self.upsert_calls = 0

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        assert project_id == "123"
        return self.document

    def upsert_items(self, *, project_id: str, items: list[DashboardItem]) -> DashboardDocument:
        assert project_id == "123"
        self.upsert_calls += 1
        self.items = items
        existing = self.document.items_by_id()
        for item in items:
            existing[item.id] = item
        sections = empty_sections()
        sections[0] = DashboardSection(key="open_candidates", title="Open Candidates", items=[])
        sections[1] = DashboardSection(
            key="in_progress",
            title="In Progress",
            items=[item for item in existing.values() if item.status == "in_progress"],
        )
        sections[2] = DashboardSection(
            key="merge_requests_opened",
            title="Merge Requests Opened",
            items=[item for item in existing.values() if item.status == "mr_opened"],
        )
        sections[3] = DashboardSection(
            key="completed",
            title="Completed",
            items=[item for item in existing.values() if item.status == "done"],
        )
        sections[5] = DashboardSection(
            key="rejected_or_ignored",
            title="Rejected Or Ignored",
            items=[item for item in existing.values() if item.status == "rejected"],
        )
        sections[6] = DashboardSection(
            key="recent_failures",
            title="Recent Failures",
            items=[item for item in existing.values() if item.status == "failed"],
        )
        self.document = DashboardDocument(
            issue_id=10,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Dashboard",
            sections=sections,
        )
        return self.document


def build_document(*, items: list[DashboardItem]) -> DashboardDocument:
    sections = empty_sections()
    sections[0] = DashboardSection(
        key="open_candidates",
        title="Open Candidates",
        items=items,
    )
    return DashboardDocument(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Dashboard",
        sections=sections,
    )


def test_mark_in_progress_stamps_run_metadata_and_preserves_existing_fields() -> None:
    dashboard_service = FakeDashboardService(build_document(items=[build_item()]))
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_in_progress(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-1",
    )

    assert result.error_message is None
    assert result.updated_item is not None
    assert result.updated_item.status == "in_progress"
    assert result.updated_item.last_run_id == "run-1"
    assert result.updated_item.status_updated_at is not None
    assert result.updated_item.validation_commands == ["uv run pytest"]
    assert result.updated_item.constraints == "Single-file only."


def test_mark_mr_opened_writes_traceability_fields() -> None:
    dashboard_service = FakeDashboardService(
        build_document(
            items=[build_item(status="in_progress").model_copy(update={"last_run_id": "run-1"})]
        )
    )
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_mr_opened(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-1",
        branch_name="ai-sonar/ax123/service",
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/1",
        merge_request_iid=1,
        commit_sha="abc123",
    )

    assert result.error_message is None
    assert result.updated_item is not None
    assert result.updated_item.status == "mr_opened"
    assert result.updated_item.branch_name == "ai-sonar/ax123/service"
    assert result.updated_item.merge_request_url is not None
    assert result.updated_item.merge_request_iid == 1
    assert result.updated_item.commit_sha == "abc123"


def test_mark_failed_preserves_existing_metadata_and_records_error_context() -> None:
    dashboard_service = FakeDashboardService(
        build_document(
            items=[
                build_item(status="in_progress").model_copy(
                    update={"branch_name": "ai-sonar/ax123/service"}
                )
            ]
        )
    )
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_failed(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-2",
        error_message="Validation failed.",
    )

    assert result.error_message is None
    assert result.updated_item is not None
    assert result.updated_item.status == "failed"
    assert result.updated_item.last_run_id == "run-2"
    assert result.updated_item.branch_name == "ai-sonar/ax123/service"
    assert result.updated_item.log_excerpt == "Validation failed."


def test_mark_done_moves_item_to_completed_and_preserves_traceability() -> None:
    dashboard_service = FakeDashboardService(
        build_document(
            items=[
                build_item(status="mr_opened").model_copy(
                    update={
                        "branch_name": "ai-sonar/ax123/service",
                        "merge_request_url": (
                            "https://gitlab.example.com/group/project/-/merge_requests/1"
                        ),
                        "commit_sha": "abc123",
                    }
                )
            ]
        )
    )
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_done(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-3",
        summary="Issue no longer needs remediation.",
    )

    assert result.error_message is None
    assert result.updated_item is not None
    assert result.updated_item.status == "done"
    assert result.updated_item.last_run_id == "run-3"
    assert result.updated_item.branch_name == "ai-sonar/ax123/service"
    assert (
        result.updated_item.merge_request_url
        == "https://gitlab.example.com/group/project/-/merge_requests/1"
    )
    assert result.updated_item.commit_sha == "abc123"
    assert result.updated_item.log_excerpt == "Issue no longer needs remediation."


def test_replayed_transition_for_same_run_is_idempotent() -> None:
    existing_item = build_item(status="mr_opened").model_copy(
        update={
            "last_run_id": "run-1",
            "branch_name": "ai-sonar/ax123/service",
            "merge_request_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
            "merge_request_iid": 1,
            "commit_sha": "abc123",
        }
    )
    dashboard_service = FakeDashboardService(build_document(items=[existing_item]))
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_mr_opened(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-1",
        branch_name="ai-sonar/ax123/service",
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/1",
        merge_request_iid=1,
        commit_sha="abc123",
    )

    assert result.error_message is None
    assert result.updated_item == existing_item
    assert dashboard_service.upsert_calls == 0


def test_update_returns_error_when_dashboard_item_is_missing() -> None:
    dashboard_service = FakeDashboardService(build_document(items=[]))
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_done(
        project_id="123",
        dashboard_item_id="missing",
        run_id="run-3",
    )

    assert result.dashboard_issue_url is None
    assert result.updated_item is None
    assert (
        result.error_message
        == "Dashboard remediation update failed: Dashboard item not found: missing"
    )
