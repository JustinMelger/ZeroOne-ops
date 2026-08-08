"""Process authorized recovery commands on one authoritative GitHub work item."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from zeroone_ops.models.github import GitHubIssueComment, GitHubIssueInfo
from zeroone_ops.models.work_item import WorkItemState
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
from zeroone_ops.services.remediation.recovery.recovery_decision_service import (
    RecoveryDecisionService,
    RecoveryRequest,
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
        matched_count = 0
        accepted_count = 0
        rejected_count = 0
        processed_references = {
            event.request_reference for event in current.work_item.recovery_events
        }
        for comment in sorted(comments, key=_comment_sort_key):
            command = self.command_parser.parse(comment.body)
            if not command.matched_prefix:
                continue
            matched_count += 1
            reference = f"github-comment-{comment.id}"
            if command.action is None or reference in processed_references:
                rejected_count += command.action is None
                continue
            occurred_at = _parse_comment_timestamp(comment.created_at)
            if occurred_at is None or _is_older_than_latest_event(current.work_item, occurred_at):
                rejected_count += 1
                continue
            if comment.author_username is None:
                rejected_count += 1
                continue
            decision = self.decision_service.decide(
                work_item=current.work_item,
                request=RecoveryRequest(
                    action=command.action,
                    actor=comment.author_username,
                    request_reference=reference,
                    expected_state_fingerprint=self.decision_service.state_fingerprint(
                        current.work_item
                    ),
                    occurred_at=occurred_at,
                ),
                policy_eligible=policy_eligible,
            )
            if not decision.accepted:
                rejected_count += 1
                continue
            if persist:
                upsert = self.work_item_service.update_existing_work_item(
                    repository_id=repository_id,
                    existing=current,
                    work_item=decision.work_item,
                )
                current = GitHubWorkItemLookupResult(
                    issue=upsert.issue,
                    work_item=upsert.work_item,
                )
            else:
                current = GitHubWorkItemLookupResult(
                    issue=current.issue,
                    work_item=decision.work_item,
                )
            processed_references.add(reference)
            accepted_count += 1
        return GitHubWorkItemRecoveryProcessResult(
            issue=current.issue,
            work_item=current.work_item,
            comment_count=comment_count,
            authorized_comment_count=authorized_comment_count,
            matched_command_count=matched_count,
            accepted_command_count=accepted_count,
            rejected_command_count=rejected_count,
        )


def _comment_sort_key(comment: GitHubIssueComment) -> tuple[datetime, int]:
    """Sort parseable timestamps before invalid ones while retaining stable comment order."""
    timestamp = _parse_comment_timestamp(comment.created_at)
    return (timestamp or datetime.max.astimezone(), comment.id)


def _parse_comment_timestamp(value: str | None) -> datetime | None:
    """Parse one GitHub comment timestamp only when it has an explicit timezone."""
    if value is None:
        return None
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo is not None else None


def _is_older_than_latest_event(work_item: WorkItemState, occurred_at: datetime) -> bool:
    """Reject comments that predate the last accepted recovery transition."""
    if not work_item.recovery_events:
        return False
    return occurred_at <= work_item.recovery_events[-1].occurred_at
