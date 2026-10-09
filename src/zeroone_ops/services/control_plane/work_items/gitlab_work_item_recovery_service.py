"""Process authorized recovery commands on one authoritative GitLab work item."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.models.work_item_recovery import AuthorizedWorkItemCommandEvent
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
from zeroone_ops.services.control_plane.work_items.work_item_recovery_coordinator import (
    WorkItemRecoveryCoordinator,
)
from zeroone_ops.services.remediation.recovery.recovery_decision_service import (
    RecoveryDecisionService,
)
from zeroone_ops.services.remediation.recovery.review_feedback_decision_service import (
    ReviewFeedbackDecisionService,
)
from zeroone_ops.services.remediation.recovery.work_item_command_decision_service import (
    WorkItemCommandDecisionService,
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
        self.review_feedback_decision_service = ReviewFeedbackDecisionService()
        self.command_decision_service = WorkItemCommandDecisionService(
            recovery_decision_service=self.decision_service,
            review_feedback_decision_service=self.review_feedback_decision_service,
        )
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

        def persist_transition(work_item: WorkItemState) -> WorkItemState:
            nonlocal current
            upsert = self.work_item_service.update_existing_work_item(
                project_id=project_id, existing=current, work_item=work_item
            )
            current = GitLabWorkItemLookupResult(issue=upsert.issue, work_item=upsert.work_item)
            return current.work_item

        outcome = WorkItemRecoveryCoordinator(
            command_parser=self.command_parser,
            command_decision_service=self.command_decision_service,
        ).process(
            work_item=existing.work_item,
            events=[
                AuthorizedWorkItemCommandEvent(
                    provider_event_id=note.id,
                    request_reference=f"gitlab-note-{note.id}",
                    body=note.body,
                    actor=note.author_username,
                    created_at=note.created_at,
                )
                for note in authorized_notes
            ],
            policy_eligible=policy_eligible,
            persist=persist,
            persist_work_item=persist_transition,
        )
        return GitLabWorkItemRecoveryProcessResult(
            issue=current.issue,
            work_item=outcome.work_item,
            note_count=len(notes),
            authorized_note_count=len(authorized_notes),
            matched_command_count=outcome.matched_command_count,
            accepted_command_count=outcome.accepted_command_count,
            rejected_command_count=outcome.rejected_command_count,
        )
