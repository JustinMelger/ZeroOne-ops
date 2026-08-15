"""Provider-local remediation control-plane adapters."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol, cast
from uuid import uuid4

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.finding import RemediationContext
from zeroone_ops.models.remediation import RemediationExecutionTarget, RemediationWorkItem
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    PublicationRetryState,
    WorkItemExecutionFailure,
    WorkItemSourceRef,
    WorkItemState,
    WorkItemStatus,
)
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.remediation_work_item_promotion_service import (
    RemediationWorkItemPromotionContext,
    RemediationWorkItemPromotionService,
)
from zeroone_ops.settings import load_github_connection_config

LOGGER = logging.getLogger(__name__)


class RemediationControlPlane(Protocol):
    """Project remediation publish lifecycle into the provider-local control plane."""

    def materialize_promoted_work_item(
        self,
        *,
        work_item: RemediationWorkItem,
        promotion_context: RemediationWorkItemPromotionContext,
    ) -> WorkItemState | None:
        """Create or update authoritative work-item state when promotion requires it."""

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
    ) -> WorkItemState | None:
        """Record that remediation publish has started."""

    def mark_execution_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
    ) -> None:
        """Best-effort transition after a promoted remediation flow fails early."""

    def mark_execution_dismissed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
    ) -> None:
        """Best-effort transition after remediation is intentionally rejected."""

    def mark_execution_completed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Best-effort transition after remediation completes without a change request."""

    def mark_publish_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        publication_retry: PublicationRetryState | None = None,
    ) -> None:
        """Best-effort transition after a failed remediation publish."""

    def sync_change_request_link(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        published_change_request: ChangeRequestInfo,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Best-effort sync of the published change request onto control-plane state."""


class NoOpRemediationControlPlane:
    """Provider-local control plane that performs no state projection."""

    def materialize_promoted_work_item(
        self,
        *,
        work_item: RemediationWorkItem,
        promotion_context: RemediationWorkItemPromotionContext,
    ) -> WorkItemState | None:
        """Ignore promotion materialization when no control plane is active."""
        del work_item, promotion_context
        return None

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
    ) -> WorkItemState | None:
        """Ignore publish-start projection when no control plane is active."""
        del selected_issue
        return None

    def mark_execution_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
    ) -> None:
        """Ignore blocked-state projection when no control plane is active."""
        del selected_issue, existing_work_item, execution_failure

    def mark_execution_dismissed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
    ) -> None:
        """Ignore dismissed-state projection when no control plane is active."""
        del selected_issue, existing_work_item, execution_failure

    def mark_execution_completed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Ignore completed-state projection when no control plane is active."""
        del selected_issue, existing_work_item

    def mark_publish_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        publication_retry: PublicationRetryState | None = None,
    ) -> None:
        """Ignore blocked-state projection when no control plane is active."""
        del selected_issue, existing_work_item, publication_retry

    def sync_change_request_link(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        published_change_request: ChangeRequestInfo,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Ignore change-request link projection when no control plane is active."""
        del selected_issue, published_change_request, existing_work_item


class WorkItemRemediationControlPlane:
    """Project remediation lifecycle through one provider-local work-item upsert operation."""

    def __init__(
        self,
        *,
        scope_id: str,
        upsert_work_item: Callable[[WorkItemState], WorkItemState],
        promotion_service: RemediationWorkItemPromotionService | None = None,
    ) -> None:
        """Initialize shared remediation projection over one authoritative work-item store."""
        self.scope_id = scope_id
        self.upsert_work_item = upsert_work_item
        self.promotion_service = promotion_service or RemediationWorkItemPromotionService()

    def materialize_promoted_work_item(
        self,
        *,
        work_item: RemediationWorkItem,
        promotion_context: RemediationWorkItemPromotionContext,
    ) -> WorkItemState | None:
        """Create or update authoritative work-item state when promoted."""
        decision = self.promotion_service.decide(
            work_item=work_item,
            context=promotion_context,
        )
        if decision.disposition != "promote":
            return None
        promoted_work_item = self._build_candidate_work_item(
            work_item=work_item,
            status="approved",
        )
        return self.upsert_work_item(promoted_work_item)

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
    ) -> WorkItemState:
        """Create or update the authoritative work item as in progress."""
        return self._upsert_work_item(
            selected_issue=selected_issue,
            status="in_progress",
            linked_change_request=None,
        )

    def mark_publish_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        publication_retry: PublicationRetryState | None = None,
    ) -> None:
        """Best-effort transition of work-item state after publish failure."""
        self.mark_execution_blocked(
            selected_issue=selected_issue,
            existing_work_item=existing_work_item,
            publication_retry=publication_retry,
        )

    def mark_execution_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        publication_retry: PublicationRetryState | None = None,
        execution_failure: WorkItemExecutionFailure | None = None,
    ) -> None:
        """Best-effort transition of work-item state after a failed execution path."""
        if existing_work_item is None:
            return
        try:
            self._upsert_work_item(
                selected_issue=selected_issue,
                status="blocked",
                linked_change_request=existing_work_item.linked_change_request,
                existing_work_item=existing_work_item,
                publication_retry=publication_retry,
                execution_failure=execution_failure,
            )
        except (GitHubClientError, GitLabClientError, RuntimeError):
            return

    def mark_execution_dismissed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
    ) -> None:
        """Best-effort transition of work-item state after rejected remediation."""
        if existing_work_item is None:
            return
        try:
            self._upsert_work_item(
                selected_issue=selected_issue,
                status="dismissed",
                linked_change_request=existing_work_item.linked_change_request,
                existing_work_item=existing_work_item,
                execution_failure=execution_failure,
            )
        except (GitHubClientError, GitLabClientError, RuntimeError):
            return

    def mark_execution_completed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Best-effort transition of work-item state after successful completion."""
        if existing_work_item is None:
            return
        try:
            self._upsert_work_item(
                selected_issue=selected_issue,
                status="completed",
                linked_change_request=existing_work_item.linked_change_request,
                existing_work_item=existing_work_item,
            )
        except (GitHubClientError, GitLabClientError, RuntimeError):
            return

    def sync_change_request_link(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        published_change_request: ChangeRequestInfo,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Best-effort sync of the linked change request onto work-item state."""
        try:
            self._upsert_work_item(
                selected_issue=selected_issue,
                status="in_progress",
                linked_change_request=published_change_request,
                existing_work_item=existing_work_item,
            )
        except (GitHubClientError, GitLabClientError, RuntimeError):
            LOGGER.warning(
                "work-item linkage sync failed after change-request publication",
                extra={
                    "change_request_url": published_change_request.web_url,
                },
                exc_info=True,
            )

    def _upsert_work_item(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        status: str,
        linked_change_request: ChangeRequestInfo | ChangeRequestRef | None,
        existing_work_item: WorkItemState | None = None,
        publication_retry: PublicationRetryState | None = None,
        execution_failure: WorkItemExecutionFailure | None = None,
    ) -> WorkItemState:
        """Create or update the authoritative provider work-item issue."""
        work_item = self._build_work_item(
            selected_issue=selected_issue,
            status=cast(WorkItemStatus, status),
            linked_change_request=linked_change_request,
            existing_work_item=existing_work_item,
            publication_retry=publication_retry,
            execution_failure=execution_failure,
        )
        return self.upsert_work_item(work_item)

    def _build_candidate_work_item(
        self,
        *,
        work_item: RemediationWorkItem,
        status: WorkItemStatus,
    ) -> WorkItemState:
        """Build canonical work-item state from a normalized remediation candidate."""
        return WorkItemState(
            work_item_id=f"work-{uuid4().hex}",
            kind="remediation",
            status=status,
            source=WorkItemSourceRef(
                source=work_item.source_type,
                source_item_key=work_item.source_ref,
                repository_scope=self.scope_id,
            ),
            summary=work_item.title,
            severity=work_item.severity,
            file_path=work_item.file_path,
            line=work_item.line,
            remediation_context=RemediationContext(
                category=work_item.remediation_category,
                diagnostic_code=work_item.rule_id,
                validation_commands=work_item.validation_commands,
                expected_change=work_item.expected_change,
                constraints=work_item.constraints,
                acceptance_criteria=work_item.acceptance_criteria,
            ),
        )

    def _build_work_item(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        status: WorkItemStatus,
        linked_change_request: ChangeRequestInfo | ChangeRequestRef | None,
        existing_work_item: WorkItemState | None,
        publication_retry: PublicationRetryState | None = None,
        execution_failure: WorkItemExecutionFailure | None = None,
    ) -> WorkItemState:
        """Build the canonical work-item state for remediation publication."""
        return WorkItemState(
            work_item_id=(
                existing_work_item.work_item_id
                if existing_work_item is not None
                else f"work-{uuid4().hex}"
            ),
            kind="remediation",
            status=status,
            source=WorkItemSourceRef(
                source=selected_issue.source_type,
                source_item_key=selected_issue.source_ref,
                repository_scope=self.scope_id,
            ),
            summary=selected_issue.title,
            severity=selected_issue.severity,
            file_path=selected_issue.file_path,
            line=selected_issue.line,
            remediation_context=RemediationContext(
                category=selected_issue.remediation_category,
                diagnostic_code=selected_issue.rule_id,
                validation_commands=selected_issue.validation_commands,
                expected_change=selected_issue.expected_change,
                constraints=selected_issue.constraints,
                acceptance_criteria=selected_issue.acceptance_criteria,
            ),
            linked_change_request=(
                None
                if linked_change_request is None
                else self._normalize_change_request_ref(linked_change_request)
            ),
            publication_retry=publication_retry,
            execution_failure=execution_failure,
        )

    def _normalize_change_request_ref(
        self,
        change_request: ChangeRequestInfo | ChangeRequestRef,
    ) -> ChangeRequestRef:
        """Return the canonical linked change-request reference."""
        if isinstance(change_request, ChangeRequestRef):
            return change_request
        return ChangeRequestRef(
            number=change_request.iid,
            web_url=change_request.web_url,
        )


class GitHubRemediationControlPlane(WorkItemRemediationControlPlane):
    """Compose shared remediation projection with GitHub work-item transport."""

    def __init__(
        self,
        *,
        work_item_service: GitHubWorkItemService,
        repository_id: str,
        promotion_service: RemediationWorkItemPromotionService | None = None,
    ) -> None:
        """Initialize GitHub-specific remediation projection."""
        self.work_item_service = work_item_service
        self.repository_id = repository_id
        super().__init__(
            scope_id=repository_id,
            upsert_work_item=lambda work_item: (
                work_item_service.upsert_work_item(
                    repository_id=repository_id,
                    work_item=work_item,
                ).work_item
            ),
            promotion_service=promotion_service,
        )


class GitLabRemediationControlPlane(WorkItemRemediationControlPlane):
    """Compose shared remediation projection with GitLab work-item transport."""

    def __init__(
        self,
        *,
        work_item_service: GitLabWorkItemService,
        project_id: str,
        promotion_service: RemediationWorkItemPromotionService | None = None,
    ) -> None:
        """Initialize GitLab-specific remediation projection."""
        self.work_item_service = work_item_service
        self.project_id = project_id
        super().__init__(
            scope_id=project_id,
            upsert_work_item=lambda work_item: (
                work_item_service.upsert_work_item(
                    project_id=project_id,
                    work_item=work_item,
                ).work_item
            ),
            promotion_service=promotion_service,
        )


def build_remediation_control_plane(
    config: AppConfig,
    *,
    github_work_item_service: GitHubWorkItemService | None = None,
    github_repository_id: str | None = None,
    gitlab_work_item_service: GitLabWorkItemService | None = None,
    gitlab_project_id: str | None = None,
) -> RemediationControlPlane:
    """Build the provider-local remediation control-plane adapter for one repo config."""
    if config.platform == "github":
        repository_id = (
            github_repository_id
            if github_repository_id is not None
            else load_github_connection_config().repository
        )
        work_item_service = github_work_item_service or GitHubWorkItemService(
            GitHubWorkItemClient(load_github_connection_config())
        )
        return GitHubRemediationControlPlane(
            work_item_service=work_item_service,
            repository_id=repository_id,
        )
    gitlab_config = config.require_gitlab_config(
        reason="GitLab work-item remediation control plane"
    )
    if (
        gitlab_config.control_plane_mode != "issues"
        or gitlab_work_item_service is None
        or gitlab_project_id is None
    ):
        return NoOpRemediationControlPlane()
    return GitLabRemediationControlPlane(
        work_item_service=gitlab_work_item_service,
        project_id=gitlab_project_id,
    )
