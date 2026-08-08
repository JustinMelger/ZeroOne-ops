"""Process authorized recovery commands on one authoritative GitLab work item."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.services.control_plane.policy.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.work_item_recovery_command_parser import (
    WorkItemRecoveryCommandParser,
)
from zeroone_ops.services.remediation.recovery.recovery_decision_service import (
    RecoveryDecisionService,
    RecoveryRequest,
)


@dataclass(frozen=True)
class GitLabWorkItemRecoveryProcessResult:
    """Summarize one recovery-command processing pass for a GitLab work item."""

    issue: GitLabIssueInfo | None
    work_item: WorkItemState | None
    note_count: int
    authorized_note_count: int
    matched_command_count: int
    accepted_command_count: int
    rejected_command_count: int


class GitLabWorkItemNoteClient(Protocol):
    """Load notes from one GitLab work-item issue."""

    def list_issue_notes(
        self,
        *,
        project_id: str,
        issue_iid: int,
    ) -> list[GitLabIssueNote]:
        """Return every note on one GitLab issue."""


class GitLabWorkItemRecoveryService:
    """Apply authorized GitLab work-item notes through shared recovery decisions."""

    def __init__(
        self,
        *,
        note_client: GitLabWorkItemNoteClient,
        note_authorization_service: GitLabPolicyNoteAuthorizationService,
        work_item_service: GitLabWorkItemService,
        decision_service: RecoveryDecisionService | None = None,
    ) -> None:
        """Initialize provider-local note processing dependencies."""
        self.note_client = note_client
        self.note_authorization_service = note_authorization_service
        self.work_item_service = work_item_service
        self.decision_service = decision_service or RecoveryDecisionService()
        self.command_parser = WorkItemRecoveryCommandParser()

    def process(
        self,
        *,
        project_id: str,
        existing: GitLabWorkItemLookupResult,
        policy_eligible: bool,
        persist: bool,
    ) -> GitLabWorkItemRecoveryProcessResult:
        """Process new authorized recovery notes for exactly one work-item issue."""
        notes = self.note_client.list_issue_notes(
            project_id=project_id,
            issue_iid=existing.issue.iid,
        )
        authorized_notes = self.note_authorization_service.authorized_notes(
            project_id=project_id,
            notes=notes,
        )
        current = existing
        processed_references = {
            event.request_reference for event in current.work_item.recovery_events
        }
        matched = accepted = rejected = 0
        for note in sorted(authorized_notes, key=_note_sort_key):
            command = self.command_parser.parse(note.body)
            if not command.matched_prefix:
                continue
            matched += 1
            reference = f"gitlab-note-{note.id}"
            occurred_at = _parse_note_timestamp(note.created_at)
            if (
                command.action is None
                or reference in processed_references
                or occurred_at is None
                or _is_older_than_latest_event(current.work_item, occurred_at)
                or note.author_username is None
            ):
                rejected += command.action is not None and reference not in processed_references
                continue
            decision = self.decision_service.decide(
                work_item=current.work_item,
                request=RecoveryRequest(
                    action=command.action,
                    actor=note.author_username,
                    request_reference=reference,
                    expected_state_fingerprint=self.decision_service.state_fingerprint(
                        current.work_item
                    ),
                    occurred_at=occurred_at,
                ),
                policy_eligible=policy_eligible,
            )
            if not decision.accepted:
                rejected += 1
                continue
            if persist:
                upsert = self.work_item_service.update_existing_work_item(
                    project_id=project_id,
                    existing=current,
                    work_item=decision.work_item,
                )
                current = GitLabWorkItemLookupResult(
                    issue=upsert.issue,
                    work_item=upsert.work_item,
                )
            else:
                current = GitLabWorkItemLookupResult(
                    issue=current.issue,
                    work_item=decision.work_item,
                )
            processed_references.add(reference)
            accepted += 1
        return GitLabWorkItemRecoveryProcessResult(
            issue=current.issue,
            work_item=current.work_item,
            note_count=len(notes),
            authorized_note_count=len(authorized_notes),
            matched_command_count=matched,
            accepted_command_count=accepted,
            rejected_command_count=rejected,
        )


def _note_sort_key(note: GitLabIssueNote) -> tuple[datetime, int]:
    timestamp = _parse_note_timestamp(note.created_at)
    return (timestamp or datetime.max.astimezone(), note.id)


def _parse_note_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None else None


def _is_older_than_latest_event(work_item: WorkItemState, occurred_at: datetime) -> bool:
    return bool(
        work_item.recovery_events and occurred_at <= work_item.recovery_events[-1].occurred_at
    )
