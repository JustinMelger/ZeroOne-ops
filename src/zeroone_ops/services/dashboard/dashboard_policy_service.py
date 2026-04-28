"""Dashboard policy-state orchestration service."""

from __future__ import annotations

from typing import Protocol

from zeroone_ops.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    DashboardPolicyState,
    DashboardPolicyView,
)
from zeroone_ops.models.gitlab import GitLabIssueNote
from zeroone_ops.services.dashboard.dashboard_policy_action_service import (
    DashboardPolicyActionService,
)


class DashboardPolicyViewBuilderProtocol(Protocol):
    """Protocol for dashboard policy-view builders."""

    def resolve_policy_state(
        self,
        policy_state: DashboardPolicyState | None,
    ) -> DashboardPolicyState:
        """Resolve canonical dashboard policy state, seeding defaults when needed."""
        ...

    def build(
        self,
        items: list[DashboardItem],
        *,
        policy_state: DashboardPolicyState | None = None,
    ) -> DashboardPolicyView:
        """Build one dashboard policy view from current dashboard items."""
        ...


class DashboardPolicyService:
    """Resolve canonical dashboard policy state and rendered policy views."""

    def __init__(
        self,
        *,
        policy_view_builder: DashboardPolicyViewBuilderProtocol | None,
        policy_action_service: DashboardPolicyActionService | None = None,
    ) -> None:
        """Initialize the dashboard policy service."""
        self.policy_view_builder = policy_view_builder
        self.policy_action_service = policy_action_service or DashboardPolicyActionService()

    def apply_to_document(
        self,
        document: DashboardDocument,
        *,
        notes: list[GitLabIssueNote] | None = None,
    ) -> DashboardDocument:
        """Return the document with canonical policy state and rendered view applied."""
        if self.policy_view_builder is None:
            return document
        policy_state = self.resolve_policy_state(document.policy_state)
        if notes:
            policy_state = self.policy_action_service.apply_actions(
                policy_state=policy_state,
                notes=notes,
            )
        policy_view = self.policy_view_builder.build(
            list(document.items_by_id().values()),
            policy_state=policy_state,
        )
        return document.model_copy(
            update={
                "policy_state": policy_state,
                "policy_view": (
                    policy_view
                    if isinstance(policy_view, DashboardPolicyView)
                    else DashboardPolicyView.model_validate(policy_view)
                ),
            }
        )

    def resolve_policy_state(
        self,
        policy_state: DashboardPolicyState | None,
    ) -> DashboardPolicyState:
        """Return the resolved canonical policy state for dashboard use."""
        if self.policy_view_builder is None:
            return policy_state or DashboardPolicyState()
        return self.policy_view_builder.resolve_policy_state(policy_state)
