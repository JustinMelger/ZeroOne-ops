from datetime import UTC, datetime

from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.models.work_item import RecoveryEvent
from zeroone_ops.services.control_plane.policy.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_recovery_service import (
    GitLabWorkItemRecoveryService,
)

from .test_gitlab_remediation_intake_service import FakeGitLabWorkItemService, _lookup_result
from .test_support import build_work_item


class FakeNoteClient:
    def __init__(self, notes: list[GitLabIssueNote], access_level: int = 40) -> None:
        self.notes = notes
        self.access_level = access_level

    def list_issue_notes(self, *, project_id: str, issue_iid: int) -> list[GitLabIssueNote]:
        del project_id, issue_iid
        return self.notes

    def get_project_member_access_level(self, *, project_id: str, user_id: int) -> int:
        del project_id, user_id
        return self.access_level


def _note(*, body: str, note_id: int = 21) -> GitLabIssueNote:
    return GitLabIssueNote(
        id=note_id,
        body=body,
        author_id=7,
        author_username="operator",
        created_at="2026-08-08T09:00:00Z",
    )


def _service(*, notes: list[GitLabIssueNote], access_level: int = 40):
    work_item = build_work_item(status="blocked")
    existing = _lookup_result(
        iid=11,
        created_at=datetime(2026, 8, 8, tzinfo=UTC),
        work_item=work_item,
    )
    work_item_service = FakeGitLabWorkItemService([existing])
    note_client = FakeNoteClient(notes, access_level=access_level)
    return (
        GitLabWorkItemRecoveryService(
            note_client=note_client,
            note_authorization_service=GitLabPolicyNoteAuthorizationService(note_client),
            work_item_service=work_item_service,  # type: ignore[arg-type]
        ),
        existing,
        work_item_service,
    )


def test_process_dismisses_a_blocked_work_item_once() -> None:
    service, existing, work_item_service = _service(
        notes=[_note(body="/zeroone remediation dismiss")]
    )

    result = service.process(
        project_id="group/project",
        existing=existing,
        policy_eligible=False,
        persist=True,
    )

    assert result.accepted_command_count == 1
    assert result.work_item is not None
    assert result.work_item.status == "dismissed"
    assert result.work_item.recovery_events[-1].request_reference == "gitlab-note-21"
    assert len(work_item_service.upserted_work_items) == 1


def test_process_requeues_only_authorized_notes() -> None:
    service, existing, work_item_service = _service(
        notes=[_note(body="/zeroone remediation requeue")],
        access_level=30,
    )

    result = service.process(
        project_id="group/project",
        existing=existing,
        policy_eligible=True,
        persist=True,
    )

    assert result.authorized_note_count == 0
    assert result.accepted_command_count == 0
    assert work_item_service.upserted_work_items == []


def test_process_skips_recorded_note_id() -> None:
    service, existing, work_item_service = _service(
        notes=[_note(body="/zeroone remediation dismiss")]
    )
    existing = existing.__class__(
        issue=existing.issue,
        work_item=existing.work_item.model_copy(
            update={
                "recovery_events": [
                    RecoveryEvent(
                        action="dismiss",
                        actor="operator",
                        request_reference="gitlab-note-21",
                        occurred_at=datetime(2026, 8, 8, 9, 0, tzinfo=UTC),
                        previous_status="blocked",
                        resulting_status="dismissed",
                        previous_attempt_number=1,
                        resulting_attempt_number=1,
                    )
                ]
            }
        ),
    )

    result = service.process(
        project_id="group/project",
        existing=existing,
        policy_eligible=True,
        persist=True,
    )

    assert result.accepted_command_count == 0
    assert work_item_service.upserted_work_items == []
