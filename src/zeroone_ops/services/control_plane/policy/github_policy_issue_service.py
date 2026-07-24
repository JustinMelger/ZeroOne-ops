"""Provider-local GitHub policy issue orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from zeroone_ops.models.dashboard import DashboardItem, DashboardPolicyState, DashboardPolicyView
from zeroone_ops.models.github import GitHubIssueComment, GitHubIssueInfo
from zeroone_ops.models.policy import PolicyActionParseResult, PolicyCommentSource
from zeroone_ops.providers.github_policy_client import GitHubPolicyClient
from zeroone_ops.services.control_plane.policy.github_policy_comment_authorization_service import (
    GitHubPolicyCommentAuthorizationService,
)
from zeroone_ops.services.control_plane.policy.github_policy_issue_parser import (
    GitHubPolicyIssueParser,
)
from zeroone_ops.services.control_plane.policy.github_policy_issue_renderer import (
    GitHubPolicyIssueRenderer,
)
from zeroone_ops.services.control_plane.policy.github_policy_issue_store import (
    GitHubPolicyIssueStore,
)
from zeroone_ops.services.control_plane.policy.policy_action_service import PolicyActionService
from zeroone_ops.services.control_plane.policy.policy_processing_service import (
    PolicyProcessingResult,
    PolicyProcessingService,
)


@dataclass(frozen=True)
class GitHubPolicyIssueProcessResult:
    """Summarize one GitHub policy issue processing pass."""

    issue: GitHubIssueInfo
    comment_count: int
    authorized_comment_count: int
    matched_prefix_count: int
    accepted_action_count: int
    rejected_prefix_count: int
    issue_changed: bool
    issue_created: bool = False
    issue_missing: bool = False
    comments: list[GitHubIssueComment] | None = None
    parsed_results: list[PolicyActionParseResult] | None = None
    initial_policy_state: DashboardPolicyState | None = None


class GitHubPolicyViewBuilderProtocol(Protocol):
    """Build GitHub policy state and compact read-only views."""

    def resolve_policy_state(
        self,
        policy_state: DashboardPolicyState | None,
    ) -> DashboardPolicyState:
        """Resolve canonical policy state, seeding defaults when needed."""
        ...

    def build(
        self,
        items: list[DashboardItem],
        *,
        policy_state: DashboardPolicyState | None = None,
    ) -> DashboardPolicyView:
        """Build one read-only policy view."""
        ...


class GitHubPolicyIssueService:
    """Load, create, process, and persist the GitHub policy issue."""

    def __init__(
        self,
        client: GitHubPolicyClient,
        *,
        parser: GitHubPolicyIssueParser | None = None,
        renderer: GitHubPolicyIssueRenderer | None = None,
        title: str = "ZeroOne Ops Policy",
        labels: list[str] | None = None,
        policy_view_builder: GitHubPolicyViewBuilderProtocol,
        policy_action_service: PolicyActionService | None = None,
        policy_processing_service: PolicyProcessingService | None = None,
        required_repository_permission: str = "admin",
    ) -> None:
        """Initialize the GitHub policy issue service."""
        self.client = client
        self.parser = parser or GitHubPolicyIssueParser()
        self.renderer = renderer or GitHubPolicyIssueRenderer()
        self.title = title
        self.labels = labels or ["zeroone-policy"]
        self.policy_view_builder = policy_view_builder
        self.issue_store = GitHubPolicyIssueStore(
            client,
            title=self.title,
            labels=self.labels,
        )
        self.policy_action_service = policy_action_service or PolicyActionService()
        self.policy_processing_service = policy_processing_service or PolicyProcessingService(
            self.policy_action_service
        )
        self.comment_authorization_service = GitHubPolicyCommentAuthorizationService(
            client,
            required_repository_permission=required_repository_permission,
        )

    def load_or_create(self, *, repository_id: str) -> GitHubIssueInfo:
        """Load the policy issue or create it if missing."""
        issue = self.issue_store.find_open_issue(repository_id=repository_id)
        if issue is None:
            policy_state = self.policy_view_builder.resolve_policy_state(None)
            policy_view = self.policy_view_builder.build([], policy_state=policy_state)
            return self.issue_store.create_issue(
                repository_id=repository_id,
                body=self.renderer.render(policy_state=policy_state, policy_view=policy_view),
            )
        policy_state = self.parser.parse_policy_state(issue.body)
        rendered = self._render_body(policy_state=policy_state)
        if rendered != issue.body:
            return self.issue_store.update_issue_body(
                repository_id=repository_id,
                issue_number=issue.number,
                body=rendered,
            )
        return issue

    def load_policy_state(
        self,
        *,
        repository_id: str,
        persist: bool,
    ) -> DashboardPolicyState:
        """Load the current persisted policy state for another control-plane workflow."""
        issue = self.issue_store.find_open_issue(repository_id=repository_id)
        if issue is None:
            policy_state = self.policy_view_builder.resolve_policy_state(None)
            if persist:
                self.issue_store.create_issue(
                    repository_id=repository_id,
                    body=self._render_body(policy_state=policy_state),
                )
            return policy_state
        policy_state = self.policy_view_builder.resolve_policy_state(
            self.parser.parse_policy_state(issue.body)
        )
        rendered = self._render_body(policy_state=policy_state)
        if persist and rendered != issue.body:
            self.issue_store.update_issue_body(
                repository_id=repository_id,
                issue_number=issue.number,
                body=rendered,
            )
        return policy_state

    def process_policy(
        self,
        *,
        repository_id: str,
        persist: bool = True,
    ) -> GitHubPolicyIssueProcessResult:
        """Load the policy issue, replay comments, and optionally persist changes."""
        issue = self.issue_store.find_open_issue(repository_id=repository_id)
        if issue is None:
            initial_policy_state = self.policy_view_builder.resolve_policy_state(None)
            body = self._render_body(policy_state=initial_policy_state)
            if persist:
                issue = self.issue_store.create_issue(
                    repository_id=repository_id,
                    body=body,
                )
            else:
                issue = GitHubIssueInfo(
                    id=0,
                    number=0,
                    web_url="",
                    title=self.issue_store.title,
                    body=body,
                )
            return GitHubPolicyIssueProcessResult(
                issue=issue,
                comment_count=0,
                authorized_comment_count=0,
                matched_prefix_count=0,
                accepted_action_count=0,
                rejected_prefix_count=0,
                issue_changed=True,
                issue_created=persist,
                issue_missing=True,
                comments=[],
                parsed_results=[],
                initial_policy_state=initial_policy_state,
            )

        comments = self.client.list_issue_comments(
            repository_id=repository_id,
            issue_number=issue.number,
        )
        authorized_comments = self.comment_authorization_service.authorized_comments(
            repository_id=repository_id,
            comments=comments,
        )
        processing_result = self._process_policy_comments(
            body=issue.body,
            comments=authorized_comments,
        )
        rendered = self._render_body(policy_state=processing_result.resolved_policy_state)
        issue_changed = rendered != issue.body
        if persist and issue_changed:
            issue = self.issue_store.update_issue_body(
                repository_id=repository_id,
                issue_number=issue.number,
                body=rendered,
            )
        return GitHubPolicyIssueProcessResult(
            issue=issue,
            comment_count=len(comments),
            authorized_comment_count=len(authorized_comments),
            matched_prefix_count=processing_result.matched_prefix_count,
            accepted_action_count=processing_result.accepted_action_count,
            rejected_prefix_count=processing_result.rejected_prefix_count,
            issue_changed=issue_changed,
            comments=comments,
            parsed_results=processing_result.parsed_results,
            initial_policy_state=processing_result.initial_policy_state,
        )

    def _process_policy_comments(
        self,
        *,
        body: str,
        comments: list[GitHubIssueComment],
    ) -> PolicyProcessingResult:
        initial_policy_state = self.policy_view_builder.resolve_policy_state(
            self.parser.parse_policy_state(body)
        )
        return self.policy_processing_service.process(
            initial_policy_state=initial_policy_state,
            sources=[_policy_source_from_comment(comment) for comment in comments],
        )

    def _render_body(self, *, policy_state: DashboardPolicyState) -> str:
        policy_view = self.policy_view_builder.build([], policy_state=policy_state)
        return self.renderer.render(policy_state=policy_state, policy_view=policy_view)


def _policy_source_from_comment(comment: GitHubIssueComment) -> PolicyCommentSource:
    """Return the provider-neutral policy source for one GitHub issue comment."""
    return PolicyCommentSource(
        id=comment.id,
        body=comment.body,
        author_username=comment.author_username,
        created_at=comment.created_at,
    )
