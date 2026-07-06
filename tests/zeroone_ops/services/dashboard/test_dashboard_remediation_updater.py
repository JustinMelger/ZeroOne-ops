from zeroone_ops.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    DashboardSection,
    empty_sections,
)
from zeroone_ops.services.dashboard.dashboard_remediation_updater import (
    DashboardRemediationUpdater,
)


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
            title="AI Code Ops Work Queue",
            sections=sections,
        )
        return self.document


class ConflictDashboardService(FakeDashboardService):
    def __init__(self, document: DashboardDocument, *, failures_before_success: int) -> None:
        super().__init__(document)
        self.failures_before_success = failures_before_success
        self.load_calls = 0

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        self.load_calls += 1
        return super().load_or_create(project_id=project_id)

    def upsert_items(self, *, project_id: str, items: list[DashboardItem]) -> DashboardDocument:
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise RuntimeError("write conflict")
        return super().upsert_items(project_id=project_id, items=items)


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
        title="AI Code Ops Work Queue",
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


def test_mark_in_progress_can_consume_retry_fields() -> None:
    dashboard_service = FakeDashboardService(
        build_document(
            items=[
                build_item().model_copy(
                    update={
                        "retry_count": 0,
                        "retry_eligible": True,
                        "retry_block_reason": "Old block reason",
                    }
                )
            ]
        )
    )
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_in_progress(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-1",
        retry_count=1,
        retry_eligible=False,
        retry_block_reason=None,
    )

    assert result.error_message is None
    assert result.updated_item is not None
    assert result.updated_item.retry_count == 1
    assert result.updated_item.retry_eligible is False
    assert result.updated_item.retry_block_reason is None


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
        branch_name="zeroone-ops/ax123/service",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/1",
        change_request_number=1,
        commit_sha="abc123",
    )

    assert result.error_message is None
    assert result.updated_item is not None
    assert result.updated_item.status == "mr_opened"
    assert result.updated_item.branch_name == "zeroone-ops/ax123/service"
    assert result.updated_item.merge_request_url is not None
    assert result.updated_item.merge_request_iid == 1
    assert result.updated_item.commit_sha == "abc123"


def test_mark_failed_preserves_existing_metadata_and_records_error_context() -> None:
    dashboard_service = FakeDashboardService(
        build_document(
            items=[
                build_item(status="in_progress").model_copy(
                    update={"branch_name": "zeroone-ops/ax123/service"}
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
    assert result.updated_item.branch_name == "zeroone-ops/ax123/service"
    assert result.updated_item.log_excerpt == "Validation failed."


def test_mark_done_moves_item_to_completed_and_preserves_traceability() -> None:
    dashboard_service = FakeDashboardService(
        build_document(
            items=[
                build_item(status="mr_opened").model_copy(
                    update={
                        "branch_name": "zeroone-ops/ax123/service",
                        "change_request_url": (
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
    assert result.updated_item.branch_name == "zeroone-ops/ax123/service"
    assert (
        result.updated_item.merge_request_url
        == "https://gitlab.example.com/group/project/-/merge_requests/1"
    )
    assert result.updated_item.commit_sha == "abc123"
    assert result.updated_item.log_excerpt == "Issue no longer needs remediation."


def test_mark_open_reopens_item_and_clears_merge_request_linkage() -> None:
    dashboard_service = FakeDashboardService(
        build_document(
            items=[
                build_item(status="mr_opened").model_copy(
                    update={
                        "branch_name": "zeroone-ops/ax123/service",
                        "change_request_url": (
                            "https://gitlab.example.com/group/project/-/merge_requests/1"
                        ),
                        "commit_sha": "abc123",
                    }
                )
            ]
        )
    )
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_open(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-4",
        summary="Merge request was closed without merge.",
    )

    assert result.error_message is None
    assert result.updated_item is not None
    assert result.updated_item.status == "open"
    assert result.updated_item.last_run_id == "run-4"
    assert result.updated_item.branch_name == "zeroone-ops/ax123/service"
    assert result.updated_item.merge_request_url is None
    assert result.updated_item.merge_request_iid is None
    assert result.updated_item.commit_sha == "abc123"
    assert result.updated_item.log_excerpt == "Merge request was closed without merge."


def test_reconciliation_updates_preserve_existing_remediation_metadata() -> None:
    dashboard_service = FakeDashboardService(
        build_document(
            items=[
                build_item(status="mr_opened").model_copy(
                    update={
                        "branch_name": "zeroone-ops/ax123/service",
                        "change_request_url": (
                            "https://gitlab.example.com/group/project/-/merge_requests/1"
                        ),
                        "change_request_number": 1,
                        "commit_sha": "abc123",
                        "validation_commands": ["uv run pytest", "uv run mypy src"],
                        "constraints": "Single-file only. No public API changes.",
                        "expected_change": "Simplify boolean comparison.",
                        "acceptance_criteria": ["Tests still pass."],
                        "upstream_active": False,
                    }
                )
            ]
        )
    )
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_open(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-5",
        summary="Merge request was closed without merge.",
    )

    assert result.error_message is None
    assert result.updated_item is not None
    assert result.updated_item.status == "open"
    assert result.updated_item.validation_commands == ["uv run pytest", "uv run mypy src"]
    assert result.updated_item.constraints == "Single-file only. No public API changes."
    assert result.updated_item.expected_change == "Simplify boolean comparison."
    assert result.updated_item.acceptance_criteria == ["Tests still pass."]
    assert result.updated_item.upstream_active is False


def test_replayed_transition_for_same_run_is_idempotent() -> None:
    existing_item = build_item(status="mr_opened").model_copy(
        update={
            "last_run_id": "run-1",
            "branch_name": "zeroone-ops/ax123/service",
            "change_request_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
            "change_request_number": 1,
            "commit_sha": "abc123",
        }
    )
    dashboard_service = FakeDashboardService(build_document(items=[existing_item]))
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_mr_opened(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-1",
        branch_name="zeroone-ops/ax123/service",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/1",
        change_request_number=1,
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


def test_update_retries_once_after_conflict_and_succeeds() -> None:
    dashboard_service = ConflictDashboardService(
        build_document(items=[build_item()]),
        failures_before_success=1,
    )
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_in_progress(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-1",
    )

    assert result.error_message is None
    assert result.updated_item is not None
    assert result.updated_item.status == "in_progress"
    assert dashboard_service.upsert_calls == 1
    assert dashboard_service.load_calls == 2


def test_update_fails_safe_after_second_conflict() -> None:
    dashboard_service = ConflictDashboardService(
        build_document(items=[build_item()]),
        failures_before_success=2,
    )
    updater = DashboardRemediationUpdater(dashboard_service)

    result = updater.mark_in_progress(
        project_id="123",
        dashboard_item_id="sonar:1",
        run_id="run-1",
    )

    assert result.dashboard_issue_url is None
    assert result.updated_item is None
    assert result.error_message == "Dashboard remediation update failed: write conflict"
    assert dashboard_service.upsert_calls == 0
    assert dashboard_service.load_calls == 2
