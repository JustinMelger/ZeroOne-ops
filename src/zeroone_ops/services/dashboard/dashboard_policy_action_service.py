"""Compatibility wrapper over the shared policy action service."""

from __future__ import annotations

from zeroone_ops.models.dashboard import DashboardPolicyState
from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.models.policy import (
    PolicyAction,
    PolicyActionParseResult,
    PolicyCommentSource,
    PolicySeverity,
)
from zeroone_ops.services.control_plane.policy.policy_action_service import (
    PolicyActionService,
)

DashboardPolicyAction = PolicyAction
DashboardPolicyActionParseResult = PolicyActionParseResult
DashboardPolicySeverity = PolicySeverity

__all__ = [
    "DashboardPolicyAction",
    "DashboardPolicyActionParseResult",
    "DashboardPolicyActionService",
    "DashboardPolicySeverity",
]


class DashboardPolicyActionService:
    """Adapt GitLab dashboard notes onto the shared policy action service."""

    def __init__(self, service: PolicyActionService | None = None) -> None:
        """Initialize the compatibility wrapper."""
        self._service = service or PolicyActionService(
            unsupported_command_hint=(
                "Unsupported policy command. Use the strict `/zeroone policy` "
                "forms shown in the dashboard legend."
            ),
            disable_severity_reason="Disabled by dashboard policy action.",
            exclude_issue_class_reason="Excluded by dashboard policy action.",
        )

    def parse_note(self, note: GitLabIssueNote) -> DashboardPolicyActionParseResult:
        """Parse one issue note into a typed policy action when valid."""
        return self._service.parse_source(_policy_source_from_note(note))

    def parse_notes(self, notes: list[GitLabIssueNote]) -> list[DashboardPolicyActionParseResult]:
        """Parse all issue notes and return matched or ignored outcomes."""
        return self._service.parse_sources([_policy_source_from_note(note) for note in notes])

    def accepted_actions(self, notes: list[GitLabIssueNote]) -> list[DashboardPolicyAction]:
        """Return accepted policy actions in note order."""
        return self._service.accepted_actions([_policy_source_from_note(note) for note in notes])

    def apply_actions(
        self,
        *,
        policy_state: DashboardPolicyState,
        notes: list[GitLabIssueNote],
    ) -> DashboardPolicyState:
        """Return the policy state after replaying accepted dashboard note actions."""
        return self._service.apply_actions(
            policy_state=policy_state,
            sources=[_policy_source_from_note(note) for note in notes],
        )

    def apply_action(
        self,
        *,
        policy_state: DashboardPolicyState,
        action: DashboardPolicyAction,
        note: GitLabIssueNote | None,
    ) -> DashboardPolicyState:
        """Return the policy state after applying one accepted action."""
        return self._service.apply_action(
            policy_state=policy_state,
            action=action,
            source=_policy_source_from_note(note) if note is not None else None,
        )

    def _note_sort_key(
        self,
        notes: list[GitLabIssueNote],
        note_id: int | None,
    ) -> tuple[int, float, str, int]:
        """Return one deterministic sort key for policy-note replay."""
        return self._service.source_sort_key(
            [_policy_source_from_note(note) for note in notes],
            note_id,
        )

    @property
    def shared_service(self) -> PolicyActionService:
        """Expose the shared service for provider-local orchestration wiring."""
        return self._service


def _policy_source_from_note(note: GitLabIssueNote) -> PolicyCommentSource:
    """Return the provider-neutral policy source for one GitLab note."""
    return PolicyCommentSource(
        id=note.id,
        body=note.body,
        author_username=note.author_username,
        created_at=note.created_at,
    )
