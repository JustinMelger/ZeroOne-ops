"""Process authorized GitLab dashboard-note remediation recovery commands."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from zeroone_ops.models.dashboard import DashboardDocument, DashboardItem
from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.models.remediation import is_remediation_eligible_category
from zeroone_ops.models.state import utc_now
from zeroone_ops.models.work_item import RecoveryEvent
from zeroone_ops.services.dashboard.dashboard_recovery_command_parser import (
    DashboardRecoveryCommandParser,
)
from zeroone_ops.services.dashboard.dashboard_recovery_state import (
    apply_work_item_recovery_state,
    dashboard_item_to_work_item_state,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardService
from zeroone_ops.services.dashboard.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
)
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)
from zeroone_ops.services.remediation.recovery.recovery_decision_service import (
    RecoveryDecisionService,
    RecoveryRequest,
)


@dataclass(frozen=True)
class DashboardRecoveryProcessResult:
    """Summarize one dashboard-note recovery processing pass."""

    document: DashboardDocument
    note_count: int
    authorized_note_count: int
    matched_command_count: int
    accepted_command_count: int
    rejected_command_count: int


@dataclass(frozen=True)
class _DashboardRecoveryCommandCounts:
    """Count dashboard recovery commands without exposing partial process results."""

    matched: int
    accepted: int
    rejected: int


class DashboardRecoveryService:
    """Apply dashboard-note recovery commands through the shared decision service."""

    def __init__(
        self,
        *,
        dashboard_service: DashboardService,
        authorization_service: GitLabPolicyNoteAuthorizationService | None = None,
        decision_service: RecoveryDecisionService | None = None,
        command_parser: DashboardRecoveryCommandParser | None = None,
        policy_service: FindingWorkflowPolicyService | None = None,
    ) -> None:
        """Initialize provider-local dashboard recovery dependencies."""
        self.dashboard_service = dashboard_service
        self.authorization_service = authorization_service or GitLabPolicyNoteAuthorizationService(
            dashboard_service.client
        )
        self.decision_service = decision_service or RecoveryDecisionService()
        self.command_parser = command_parser or DashboardRecoveryCommandParser()
        self.policy_service = policy_service or FindingWorkflowPolicyService()

    def process(
        self,
        *,
        project_id: str,
        run_id: str,
        persist: bool,
    ) -> DashboardRecoveryProcessResult:
        """Process new authorized recovery commands on the dashboard issue."""
        document = self.dashboard_service.load_or_create(project_id=project_id)
        notes = self.dashboard_service.client.list_issue_notes(
            project_id=project_id,
            issue_iid=document.issue_iid,
        )
        authorized_notes = self.authorization_service.authorized_notes(
            project_id=project_id,
            notes=notes,
        )
        counts, updated_items = self._process_authorized_notes(
            document=document,
            notes=authorized_notes,
            run_id=run_id,
        )
        if updated_items:
            document = _apply_updated_items(document=document, items=updated_items)
        if persist and updated_items:
            document = self.dashboard_service.upsert_items(
                project_id=project_id,
                items=list(updated_items.values()),
            )
        return DashboardRecoveryProcessResult(
            document=document,
            note_count=len(notes),
            authorized_note_count=len(authorized_notes),
            matched_command_count=counts.matched,
            accepted_command_count=counts.accepted,
            rejected_command_count=counts.rejected,
        )

    def _process_authorized_notes(
        self,
        *,
        document: DashboardDocument,
        notes: list[GitLabIssueNote],
        run_id: str,
    ) -> tuple[_DashboardRecoveryCommandCounts, dict[str, DashboardItem]]:
        """Apply ordered new commands while preserving replay and stale guards."""
        items_by_id = document.items_by_id()
        updated_items: dict[str, DashboardItem] = {}
        matched_count = 0
        accepted_count = 0
        rejected_count = 0
        for note in sorted(notes, key=_note_sort_key):
            command = self.command_parser.parse(note.body)
            if not command.matched_prefix:
                continue
            matched_count += 1
            if command.item_id is None or command.action is None:
                rejected_count += 1
                continue
            item = items_by_id.get(command.item_id)
            if item is None or not is_remediation_eligible_category(item.type):
                rejected_count += 1
                continue
            reference = f"gitlab-note-{note.id}"
            try:
                work_item = dashboard_item_to_work_item_state(item)
            except ValueError:
                rejected_count += 1
                continue
            if reference in {event.request_reference for event in work_item.recovery_events}:
                continue
            occurred_at = _parse_note_timestamp(note.created_at)
            if (
                occurred_at is None
                or _is_older_than_latest_event(work_item.recovery_events, occurred_at)
                or _predates_current_blocked_state(item, occurred_at)
                or note.author_username is None
            ):
                rejected_count += 1
                continue
            decision = self.decision_service.decide(
                work_item=work_item,
                request=RecoveryRequest(
                    action=command.action,
                    actor=note.author_username,
                    request_reference=reference,
                    expected_state_fingerprint=self.decision_service.state_fingerprint(work_item),
                    occurred_at=occurred_at,
                ),
                policy_eligible=self.policy_service.is_work_item_eligible(
                    work_item=work_item,
                    policy_state=document.policy_state,
                ),
            )
            if not decision.accepted:
                rejected_count += 1
                continue
            updated_item = apply_work_item_recovery_state(item=item, work_item=decision.work_item)
            updated_item = updated_item.model_copy(
                update={
                    "last_run_id": run_id,
                    "status_updated_at": utc_now(),
                }
            )
            items_by_id[item.id] = updated_item
            updated_items[item.id] = updated_item
            accepted_count += 1
        return (
            _DashboardRecoveryCommandCounts(
                matched=matched_count,
                accepted=accepted_count,
                rejected=rejected_count,
            ),
            updated_items,
        )


def _apply_updated_items(
    *,
    document: DashboardDocument,
    items: dict[str, DashboardItem],
) -> DashboardDocument:
    """Project accepted command state into a document for dry-run visibility."""
    return document.model_copy(
        update={
            "sections": [
                section.model_copy(
                    update={"items": [items.get(item.id, item) for item in section.items]}
                )
                for section in document.sections
            ]
        }
    )


def _note_sort_key(note: GitLabIssueNote) -> tuple[datetime, int]:
    """Sort parseable timestamps before invalid ones while retaining note order."""
    timestamp = _parse_note_timestamp(note.created_at)
    return (timestamp or datetime.max.astimezone(), note.id)


def _parse_note_timestamp(value: str | None) -> datetime | None:
    """Parse one GitLab note timestamp only when it has an explicit timezone."""
    if value is None:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None else None


def _is_older_than_latest_event(
    events: list[RecoveryEvent],
    occurred_at: datetime,
) -> bool:
    """Reject notes that predate the most recent accepted recovery transition."""
    if not events:
        return False
    return occurred_at <= events[-1].occurred_at


def _predates_current_blocked_state(item: DashboardItem, occurred_at: datetime) -> bool:
    """Reject a historical command issued before the current blocked state began."""
    if item.status != "failed" or item.status_updated_at is None:
        return False
    return occurred_at <= item.status_updated_at
