"""Provider-local GitLab policy issue orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from zeroone_ops.models.dashboard import DashboardItem, DashboardPolicyState, DashboardPolicyView
from zeroone_ops.models.gitlab import GitLabIssueInfo, GitLabIssueNote
from zeroone_ops.models.policy import PolicyActionParseResult, PolicyCommentSource
from zeroone_ops.providers.gitlab_policy_client import GitLabPolicyClient
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_parser import (
    GitLabPolicyIssueParser,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_store import (
    GitLabPolicyIssueStore,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_note_authorization_service import (
    GitLabPolicyNoteAuthorizationService,
)
from zeroone_ops.services.control_plane.policy.policy_action_service import PolicyActionService
from zeroone_ops.services.control_plane.policy.policy_issue_renderer import (
    PolicyIssueRenderer,
)
from zeroone_ops.services.control_plane.policy.policy_processing_service import (
    PolicyProcessingResult,
    PolicyProcessingService,
)


@dataclass(frozen=True)
class GitLabPolicyIssueProcessResult:
    """Summarize one GitLab policy issue processing pass."""

    issue: GitLabIssueInfo
    note_count: int
    authorized_note_count: int
    matched_prefix_count: int
    accepted_action_count: int
    rejected_prefix_count: int
    issue_changed: bool
    issue_created: bool = False
    issue_missing: bool = False
    notes: list[GitLabIssueNote] | None = None
    parsed_results: list[PolicyActionParseResult] | None = None
    initial_policy_state: DashboardPolicyState | None = None


class GitLabPolicyViewBuilderProtocol(Protocol):
    """Build canonical policy state and its compact read-only view."""

    def resolve_policy_state(
        self,
        policy_state: DashboardPolicyState | None,
    ) -> DashboardPolicyState:
        """Resolve canonical policy state, seeding defaults when required."""

    def build(
        self,
        items: list[DashboardItem],
        *,
        policy_state: DashboardPolicyState | None = None,
    ) -> DashboardPolicyView:
        """Build one read-only policy view."""


class GitLabPolicyIssueService:
    """Load, create, and persist the authoritative GitLab policy issue."""

    def __init__(
        self,
        client: GitLabPolicyClient,
        *,
        policy_view_builder: GitLabPolicyViewBuilderProtocol,
        parser: GitLabPolicyIssueParser | None = None,
        renderer: PolicyIssueRenderer | None = None,
        title: str = "ZeroOne Ops Policy",
        labels: list[str] | None = None,
        policy_action_service: PolicyActionService | None = None,
        policy_processing_service: PolicyProcessingService | None = None,
        note_authorization_service: GitLabPolicyNoteAuthorizationService | None = None,
    ) -> None:
        """Initialize the GitLab policy issue service."""
        self.parser = parser or GitLabPolicyIssueParser()
        self.renderer = renderer or PolicyIssueRenderer()
        self.policy_view_builder = policy_view_builder
        self.issue_store = GitLabPolicyIssueStore(
            client,
            title=title,
            labels=labels or ["zeroone-policy"],
        )
        self.policy_action_service = policy_action_service or PolicyActionService()
        self.policy_processing_service = policy_processing_service or PolicyProcessingService(
            self.policy_action_service
        )
        self.note_authorization_service = (
            note_authorization_service or GitLabPolicyNoteAuthorizationService(client)
        )

    def load_or_create(self, *, project_id: str) -> GitLabIssueInfo:
        """Load the policy issue or create it with bootstrap policy state."""
        issue = self.issue_store.find_open_issue(project_id=project_id)
        if issue is None:
            policy_state = self.policy_view_builder.resolve_policy_state(None)
            return self.issue_store.create_issue(
                project_id=project_id,
                body=self._render_body(policy_state),
            )
        policy_state = self.policy_view_builder.resolve_policy_state(
            self.parser.parse_policy_state(issue.description)
        )
        body = self._render_body(policy_state)
        if body != issue.description:
            return self.issue_store.update_issue_body(
                project_id=project_id,
                issue=issue,
                body=body,
            )
        return issue

    def load_policy_state(self, *, project_id: str, persist: bool) -> DashboardPolicyState:
        """Return policy state for shared finding and remediation workflows."""
        issue = self.issue_store.find_open_issue(project_id=project_id)
        if issue is None:
            policy_state = self.policy_view_builder.resolve_policy_state(None)
            if persist:
                self.issue_store.create_issue(
                    project_id=project_id,
                    body=self._render_body(policy_state),
                )
            return policy_state
        policy_state = self.policy_view_builder.resolve_policy_state(
            self.parser.parse_policy_state(issue.description)
        )
        body = self._render_body(policy_state)
        if persist and body != issue.description:
            self.issue_store.update_issue_body(project_id=project_id, issue=issue, body=body)
        return policy_state

    def process_policy(
        self,
        *,
        project_id: str,
        persist: bool = True,
    ) -> GitLabPolicyIssueProcessResult:
        """Replay authorized policy issue notes and optionally persist the result."""
        issue = self.issue_store.find_open_issue(project_id=project_id)
        if issue is None:
            initial_policy_state = self.policy_view_builder.resolve_policy_state(None)
            body = self._render_body(initial_policy_state)
            if persist:
                issue = self.issue_store.create_issue(project_id=project_id, body=body)
            else:
                issue = GitLabIssueInfo(
                    id=0,
                    iid=0,
                    web_url="",
                    title=self.issue_store.title,
                    description=body,
                )
            return GitLabPolicyIssueProcessResult(
                issue=issue,
                note_count=0,
                authorized_note_count=0,
                matched_prefix_count=0,
                accepted_action_count=0,
                rejected_prefix_count=0,
                issue_changed=True,
                issue_created=persist,
                issue_missing=True,
                notes=[],
                parsed_results=[],
                initial_policy_state=initial_policy_state,
            )

        notes = self.issue_store.client.list_issue_notes(
            project_id=project_id,
            issue_iid=issue.iid,
        )
        authorized_notes = self.note_authorization_service.authorized_notes(
            project_id=project_id,
            notes=notes,
        )
        processing_result = self._process_policy_notes(
            body=issue.description,
            notes=authorized_notes,
        )
        body = self._render_body(processing_result.resolved_policy_state)
        issue_changed = body != issue.description
        if persist and issue_changed:
            issue = self.issue_store.update_issue_body(
                project_id=project_id,
                issue=issue,
                body=body,
            )
        return GitLabPolicyIssueProcessResult(
            issue=issue,
            note_count=len(notes),
            authorized_note_count=len(authorized_notes),
            matched_prefix_count=processing_result.matched_prefix_count,
            accepted_action_count=processing_result.accepted_action_count,
            rejected_prefix_count=processing_result.rejected_prefix_count,
            issue_changed=issue_changed,
            notes=notes,
            parsed_results=processing_result.parsed_results,
            initial_policy_state=processing_result.initial_policy_state,
        )

    def _process_policy_notes(
        self,
        *,
        body: str,
        notes: list[GitLabIssueNote],
    ) -> PolicyProcessingResult:
        """Apply authorized GitLab notes through the shared replay service."""
        initial_policy_state = self.policy_view_builder.resolve_policy_state(
            self.parser.parse_policy_state(body)
        )
        return self.policy_processing_service.process(
            initial_policy_state=initial_policy_state,
            sources=[_policy_source_from_note(note) for note in notes],
        )

    def _render_body(self, policy_state: DashboardPolicyState) -> str:
        """Render one compact policy issue body from canonical state."""
        policy_view = self.policy_view_builder.build([], policy_state=policy_state)
        return self.renderer.render(policy_state=policy_state, policy_view=policy_view)


def _policy_source_from_note(note: GitLabIssueNote) -> PolicyCommentSource:
    """Return the provider-neutral policy source for one GitLab issue note."""
    return PolicyCommentSource(
        id=note.id,
        body=note.body,
        author_username=note.author_username,
        created_at=note.created_at,
    )
