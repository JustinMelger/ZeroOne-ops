"""Process authorized recovery commands on one authoritative GitHub work item."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from zeroone_ops.models.github import GitHubIssueComment, GitHubIssueInfo
from zeroone_ops.models.work_item import WorkItemState
from zeroone_ops.models.work_item_recovery import AuthorizedWorkItemCommandEvent
from zeroone_ops.services.control_plane.github_comment_authorization_service import (
    GitHubCommentAuthorizationService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
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


class GitHubWorkItemCommentClient(Protocol):
    """Load issue comments through provider-local work-item transport."""

    def list_issue_comments(
        self,
        *,
        repository_id: str,
        issue_number: int,
    ) -> list[GitHubIssueComment]:
        """Return all comments on one GitHub issue."""


@dataclass(frozen=True)
class GitHubWorkItemRecoveryProcessResult:
    """Summarize one recovery-command processing pass for one issue."""

    issue: GitHubIssueInfo | None
    work_item: WorkItemState | None
    comment_count: int
    authorized_comment_count: int
    matched_command_count: int
    accepted_command_count: int
    rejected_command_count: int


class GitHubWorkItemRecoveryService:
    """Apply GitHub work-item comments through the shared recovery decision contract."""

    def __init__(
        self,
        *,
        comment_client: GitHubWorkItemCommentClient,
        comment_authorization_service: GitHubCommentAuthorizationService,
        work_item_service: GitHubWorkItemService,
        decision_service: RecoveryDecisionService | None = None,
        command_parser: WorkItemRecoveryCommandParser | None = None,
    ) -> None:
        """Initialize provider-local comment processing dependencies."""
        self.comment_client = comment_client
        self.comment_authorization_service = comment_authorization_service
        self.work_item_service = work_item_service
        self.decision_service = decision_service or RecoveryDecisionService()
        self.review_feedback_decision_service = ReviewFeedbackDecisionService()
        self.command_decision_service = WorkItemCommandDecisionService(
            recovery_decision_service=self.decision_service,
            review_feedback_decision_service=self.review_feedback_decision_service,
        )
        self.command_parser = command_parser or WorkItemRecoveryCommandParser()

    def process(
        self,
        *,
        repository_id: str,
        issue_number: int,
        comment_id: int,
        policy_eligible: bool,
        persist: bool,
    ) -> GitHubWorkItemRecoveryProcessResult:
        """Process new authorized recovery commands for exactly one work-item issue."""
        existing = self._find_work_item(repository_id=repository_id, issue_number=issue_number)
        if existing is None:
            return GitHubWorkItemRecoveryProcessResult(
                issue=None,
                work_item=None,
                comment_count=0,
                authorized_comment_count=0,
                matched_command_count=0,
                accepted_command_count=0,
                rejected_command_count=0,
            )
        comments = self.comment_client.list_issue_comments(
            repository_id=repository_id,
            issue_number=issue_number,
        )
        authorized_comments = self.comment_authorization_service.authorized_comments(
            repository_id=repository_id,
            comments=[comment for comment in comments if comment.id == comment_id],
        )
        return self._process_authorized_comments(
            repository_id=repository_id,
            existing=existing,
            comments=authorized_comments,
            comment_count=len(comments),
            authorized_comment_count=len(authorized_comments),
            policy_eligible=policy_eligible,
            persist=persist,
        )

    def _find_work_item(
        self,
        *,
        repository_id: str,
        issue_number: int,
    ) -> GitHubWorkItemLookupResult | None:
        """Return only the authoritative open work item for the requested issue number."""
        return next(
            (
                result
                for result in self.work_item_service.list_open_work_items(
                    repository_id=repository_id
                )
                if result.issue.number == issue_number
            ),
            None,
        )

    def _process_authorized_comments(
        self,
        *,
        repository_id: str,
        existing: GitHubWorkItemLookupResult,
        comments: list[GitHubIssueComment],
        comment_count: int,
        authorized_comment_count: int,
        policy_eligible: bool,
        persist: bool,
    ) -> GitHubWorkItemRecoveryProcessResult:
        """Apply ordered new commands without replaying recorded recovery events."""
        current = existing

        def persist_transition(work_item: WorkItemState) -> WorkItemState:
            nonlocal current
            upsert = self.work_item_service.update_existing_work_item(
                repository_id=repository_id, existing=current, work_item=work_item
            )
            current = GitHubWorkItemLookupResult(issue=upsert.issue, work_item=upsert.work_item)
            return current.work_item

        outcome = WorkItemRecoveryCoordinator(
            command_parser=self.command_parser,
            command_decision_service=self.command_decision_service,
        ).process(
            work_item=existing.work_item,
            events=[
                AuthorizedWorkItemCommandEvent(
                    provider_event_id=comment.id,
                    request_reference=f"github-comment-{comment.id}",
                    body=comment.body,
                    actor=comment.author_username,
                    created_at=comment.created_at,
                )
                for comment in comments
            ],
            policy_eligible=policy_eligible,
            persist=persist,
            persist_work_item=persist_transition,
        )
        return GitHubWorkItemRecoveryProcessResult(
            issue=current.issue,
            work_item=outcome.work_item,
            comment_count=comment_count,
            authorized_comment_count=authorized_comment_count,
            matched_command_count=outcome.matched_command_count,
            accepted_command_count=outcome.accepted_command_count,
            rejected_command_count=outcome.rejected_command_count,
        )
