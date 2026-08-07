from datetime import UTC, datetime
from typing import cast

from zeroone_ops.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    DashboardSection,
    DashboardSeverityPolicyStateEntry,
)
from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.services.dashboard.dashboard_recovery_service import (
    DashboardRecoveryService,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.dashboard.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
)


class FakeDashboardClient:
    def __init__(self, notes: list[GitLabIssueNote]) -> None:
        self.notes = notes

    def list_issue_notes(self, *, project_id: str, issue_iid: int) -> list[GitLabIssueNote]:
        del project_id, issue_iid
        return list(self.notes)


class FakeDashboardService:
    def __init__(self, document: DashboardDocument, notes: list[GitLabIssueNote]) -> None:
        self.document = document
        self.client = FakeDashboardClient(notes)
        self.upserted_items: list[DashboardItem] = []

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        del project_id
        return self.document

    def upsert_items(
        self,
        *,
        project_id: str,
        items: list[DashboardItem],
    ) -> DashboardDocument:
        del project_id
        self.upserted_items.extend(items)
        by_id = self.document.items_by_id()
        by_id.update({item.id: item for item in items})
        self.document = self.document.model_copy(
            update={
                "sections": [
                    section.model_copy(update={"items": [by_id[item.id] for item in section.items]})
                    for section in self.document.sections
                ]
            }
        )
        return self.document


class AllowAllAuthorizationService:
    def authorized_notes(
        self,
        *,
        project_id: str,
        notes: list[GitLabIssueNote],
    ) -> list[GitLabIssueNote]:
        del project_id
        return notes


def build_item(*, item_id: str = "sonar:AX-123") -> DashboardItem:
    return DashboardItem(
        id=item_id,
        source="sonarqube",
        type="static_analysis_fix",
        status="failed",
        title="Use direct truthiness.",
        summary="Avoid comparing a condition with True.",
        priority="medium",
        source_reference="AX-123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        automation_severity="medium",
        branch_name="zeroone-ops/sonarqube/ax-123/service",
        commit_sha="abc123",
        change_request_number=17,
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/17",
    )


def build_document(item: DashboardItem) -> DashboardDocument:
    return DashboardDocument(
        issue_id=1,
        issue_iid=2,
        issue_url="https://gitlab.example.com/group/project/-/issues/2",
        title="ZeroOne Ops dashboard",
        sections=[DashboardSection(key="recent_failures", title="Recent Failures", items=[item])],
        policy_state={
            "severity_policy": [DashboardSeverityPolicyStateEntry(severity="medium", enabled=True)]
        },
    )


def build_note(*, body: str, note_id: int = 11) -> GitLabIssueNote:
    return GitLabIssueNote(
        id=note_id,
        body=body,
        author_id=42,
        author_username="operator",
        created_at="2026-08-07T09:00:00Z",
    )


def build_service(
    *,
    document: DashboardDocument,
    notes: list[GitLabIssueNote],
) -> tuple[DashboardRecoveryService, FakeDashboardService]:
    dashboard_service = FakeDashboardService(document, notes)
    return (
        DashboardRecoveryService(
            dashboard_service=cast(DashboardService, dashboard_service),
            authorization_service=cast(
                GitLabPolicyNoteAuthorizationService,
                AllowAllAuthorizationService(),
            ),
        ),
        dashboard_service,
    )


def test_process_requeues_an_authorized_fresh_attempt() -> None:
    item = build_item()
    service, dashboard_service = build_service(
        document=build_document(item),
        notes=[build_note(body="/zeroone remediation sonar:AX-123 requeue")],
    )

    result = service.process(project_id="123", run_id="run-1", persist=True)

    assert result.accepted_command_count == 1
    assert result.rejected_command_count == 0
    updated = dashboard_service.upserted_items[0]
    assert updated.status == "open"
    assert updated.attempt_number == 2
    assert updated.change_request_url is None
    assert updated.recovery_events[-1].plan == "start_fresh"


def test_process_dismisses_an_authorized_blocked_item() -> None:
    item = build_item()
    service, dashboard_service = build_service(
        document=build_document(item),
        notes=[build_note(body="/zeroone remediation sonar:AX-123 dismiss")],
    )

    result = service.process(project_id="123", run_id="run-1", persist=True)

    assert result.accepted_command_count == 1
    updated = dashboard_service.upserted_items[0]
    assert updated.status == "rejected"
    assert updated.recovery_events[-1].action == "dismiss"


def test_process_rejects_a_command_that_predates_the_current_blocked_state() -> None:
    item = build_item().model_copy(
        update={"status_updated_at": datetime(2026, 8, 7, 10, 0, tzinfo=UTC)}
    )
    service, dashboard_service = build_service(
        document=build_document(item),
        notes=[build_note(body="/zeroone remediation sonar:AX-123 dismiss")],
    )

    result = service.process(project_id="123", run_id="run-1", persist=True)

    assert result.accepted_command_count == 0
    assert result.rejected_command_count == 1
    assert dashboard_service.upserted_items == []


def test_process_rejects_unknown_item_without_updating_the_dashboard() -> None:
    service, dashboard_service = build_service(
        document=build_document(build_item()),
        notes=[build_note(body="/zeroone remediation unknown requeue")],
    )

    result = service.process(project_id="123", run_id="run-1", persist=True)

    assert result.accepted_command_count == 0
    assert result.rejected_command_count == 1
    assert dashboard_service.upserted_items == []
