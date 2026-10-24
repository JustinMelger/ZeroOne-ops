"""Provider-local remediation control-plane adapters."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol, TypedDict, cast
from uuid import uuid4

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.finding import RemediationContext
from zeroone_ops.models.remediation import (
    RemediationCompletionRequest,
    RemediationCompletionResult,
    RemediationExecutionTarget,
)
from zeroone_ops.models.state import utc_now
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    PublicationRetryState,
    WorkItemExecutionFailure,
    WorkItemSemanticSafety,
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
from zeroone_ops.services.control_plane.work_items.work_item_state_merge import (
    merge_remediation_work_item_state,
)
from zeroone_ops.settings import load_github_connection_config

LOGGER = logging.getLogger(__name__)


class _BatchAttemptArguments(TypedDict, total=False):
    """Supply batch attempt identity without changing single-record field presence."""

    attempt_number: int


class RemediationControlPlane(Protocol):
    """Project remediation publish lifecycle into the provider-local control plane."""

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> WorkItemState | None:
        """Record that remediation publish has started."""

    def mark_execution_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        publication_retry: PublicationRetryState | None = None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Best-effort transition after a promoted remediation flow fails early."""

    def mark_execution_dismissed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Best-effort transition after remediation is intentionally rejected."""

    def mark_review_feedback_required(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Restore actionable review feedback after a failed revision."""

    def mark_execution_completed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Best-effort transition after remediation completes without a change request."""

    def complete_absent_batch(
        self, *, selected_issue: RemediationExecutionTarget, existing_work_item: WorkItemState
    ) -> RemediationCompletionResult:
        """Revalidate absence at authoritative storage and report the actual outcome."""

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
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Best-effort sync of the published change request onto control-plane state."""


class NoOpRemediationControlPlane:
    """Provider-local control plane that performs no state projection."""

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> WorkItemState | None:
        """Ignore publish-start projection when no control plane is active."""
        del selected_issue, semantic_safety
        return None

    def mark_execution_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        publication_retry: PublicationRetryState | None = None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Ignore blocked-state projection when no control plane is active."""
        del (
            selected_issue,
            existing_work_item,
            execution_failure,
            semantic_safety,
            publication_retry,
        )

    def mark_execution_dismissed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Ignore dismissed-state projection when no control plane is active."""
        del selected_issue, existing_work_item, execution_failure, semantic_safety

    def mark_review_feedback_required(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Ignore revision failure projection when no control plane is active."""
        del selected_issue, existing_work_item, execution_failure, semantic_safety

    def mark_execution_completed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Ignore completed-state projection when no control plane is active."""
        del selected_issue, existing_work_item

    def complete_absent_batch(
        self, *, selected_issue: RemediationExecutionTarget, existing_work_item: WorkItemState
    ) -> RemediationCompletionResult:
        """Never claim durable completion when no control plane is active."""
        del selected_issue, existing_work_item
        return RemediationCompletionResult(False, "Batch completion storage is unavailable.")

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
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Ignore change-request link projection when no control plane is active."""
        del selected_issue, published_change_request, existing_work_item, semantic_safety


class WorkItemRemediationControlPlane:
    """Project remediation lifecycle through one provider-local work-item upsert operation."""

    def __init__(
        self,
        *,
        scope_id: str,
        upsert_work_item: Callable[[WorkItemState], WorkItemState],
        complete_absent_batch: Callable[[RemediationCompletionRequest], RemediationCompletionResult]
        | None = None,
    ) -> None:
        """Initialize shared remediation projection over one authoritative work-item store."""
        self.scope_id = scope_id
        self.upsert_work_item = upsert_work_item
        self._complete_absent_batch = complete_absent_batch

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> WorkItemState:
        """Create or update the authoritative work item as in progress."""
        return self._upsert_work_item(
            selected_issue=selected_issue,
            status="in_progress",
            linked_change_request=None,
            semantic_safety=semantic_safety,
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
        semantic_safety: WorkItemSemanticSafety | None = None,
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
                semantic_safety=semantic_safety,
            )
        except (GitHubClientError, GitLabClientError, RuntimeError):
            return

    def mark_review_feedback_required(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Restore linked review-feedback state instead of blocking a failed revision."""
        if existing_work_item is None:
            return
        try:
            self._upsert_work_item(
                selected_issue=selected_issue,
                status="review_feedback_required",
                linked_change_request=existing_work_item.linked_change_request,
                existing_work_item=existing_work_item,
                execution_failure=execution_failure,
                semantic_safety=semantic_safety,
            )
        except (GitHubClientError, GitLabClientError, RuntimeError):
            return

    def mark_execution_dismissed(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety: WorkItemSemanticSafety | None = None,
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
                semantic_safety=semantic_safety,
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
        if selected_issue.batch is not None:
            self.complete_absent_batch(
                selected_issue=selected_issue, existing_work_item=existing_work_item
            )
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

    def complete_absent_batch(
        self, *, selected_issue: RemediationExecutionTarget, existing_work_item: WorkItemState
    ) -> RemediationCompletionResult:
        """Recheck current absence and execution ownership before updating existing authority."""
        if self._complete_absent_batch is None:
            return RemediationCompletionResult(False, "Batch completion storage is unavailable.")

        requested = self._build_work_item(
            selected_issue=selected_issue,
            status="completed",
            linked_change_request=existing_work_item.linked_change_request,
            existing_work_item=existing_work_item,
        )
        try:
            result = self._complete_absent_batch(
                RemediationCompletionRequest(
                    work_item=requested, expected_claim=existing_work_item.claim
                )
            )
        except (GitHubClientError, GitLabClientError, RuntimeError, ValueError):
            LOGGER.warning("work-item batch absence completion failed", exc_info=True)
            return RemediationCompletionResult(False, "Batch completion could not be confirmed.")

        if not result.completed:
            LOGGER.warning(
                "work-item batch absence completion retained authority: %s", result.message
            )
        return result

    def sync_change_request_link(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        published_change_request: ChangeRequestInfo,
        existing_work_item: WorkItemState | None,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> None:
        """Best-effort sync of the linked change request onto work-item state."""
        try:
            self._upsert_work_item(
                selected_issue=selected_issue,
                status="in_progress",
                linked_change_request=published_change_request,
                existing_work_item=existing_work_item,
                semantic_safety=semantic_safety,
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
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> WorkItemState:
        """Create or update the authoritative provider work-item issue."""
        work_item = self._build_work_item(
            selected_issue=selected_issue,
            status=cast(WorkItemStatus, status),
            linked_change_request=linked_change_request,
            existing_work_item=existing_work_item,
            publication_retry=publication_retry,
            execution_failure=execution_failure,
            semantic_safety=semantic_safety,
        )
        return self.upsert_work_item(work_item)

    def _build_work_item(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        status: WorkItemStatus,
        linked_change_request: ChangeRequestInfo | ChangeRequestRef | None,
        existing_work_item: WorkItemState | None,
        publication_retry: PublicationRetryState | None = None,
        execution_failure: WorkItemExecutionFailure | None = None,
        semantic_safety: WorkItemSemanticSafety | None = None,
    ) -> WorkItemState:
        """Build the canonical work-item state for remediation publication."""
        attempt_arguments: _BatchAttemptArguments = {}
        if selected_issue.batch_attempt is not None:
            attempt_arguments["attempt_number"] = selected_issue.batch_attempt.attempt_number
        elif selected_issue.batch is not None and existing_work_item is not None:
            attempt_arguments["attempt_number"] = existing_work_item.attempt_number
        return WorkItemState(
            **attempt_arguments,
            batch=selected_issue.batch
            if selected_issue.batch is not None
            else (existing_work_item.batch if existing_work_item is not None else None),
            batch_attempt=selected_issue.batch_attempt
            if selected_issue.batch_attempt is not None
            else (existing_work_item.batch_attempt if existing_work_item is not None else None),
            resolution=(
                "no_longer_detected"
                if status == "completed"
                and selected_issue.batch is not None
                and all(
                    o.last_confirmed_presence == "absent" and o.freshness == "current"
                    for o in selected_issue.batch.observations
                )
                else None
            ),
            work_item_id=(
                existing_work_item.work_item_id
                if existing_work_item is not None
                else selected_issue.item_id
                if selected_issue.batch is not None
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
            projected_review=(
                None if existing_work_item is None else existing_work_item.projected_review
            ),
            review_revision_request=(
                None
                if existing_work_item is None
                or status in {"in_progress", "review_feedback_required"}
                else existing_work_item.review_revision_request
            ),
            claim=None,
            review_action_required_at=(
                utc_now()
                if status == "review_feedback_required"
                else None
                if existing_work_item is None
                else existing_work_item.review_action_required_at
            ),
            last_revision_command=(
                None
                if existing_work_item is None
                else existing_work_item.last_revision_command
                or existing_work_item.review_revision_request
            ),
            publication_retry=publication_retry,
            execution_failure=execution_failure,
            semantic_safety=(
                semantic_safety
                if semantic_safety is not None
                else None
                if existing_work_item is None
                else existing_work_item.semantic_safety
            ),
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
    ) -> None:
        """Initialize GitHub-specific remediation projection."""
        self.work_item_service = work_item_service
        self.repository_id = repository_id
        super().__init__(
            scope_id=repository_id,
            complete_absent_batch=lambda request: work_item_service.complete_absent_batch(
                repository_id=repository_id, request=request
            ),
            upsert_work_item=lambda work_item: (
                work_item_service.upsert_work_item(
                    repository_id=repository_id,
                    work_item=work_item,
                    state_merge=merge_remediation_work_item_state,
                ).work_item
            ),
        )


class GitLabRemediationControlPlane(WorkItemRemediationControlPlane):
    """Compose shared remediation projection with GitLab work-item transport."""

    def __init__(
        self,
        *,
        work_item_service: GitLabWorkItemService,
        project_id: str,
    ) -> None:
        """Initialize GitLab-specific remediation projection."""
        self.work_item_service = work_item_service
        self.project_id = project_id
        super().__init__(
            scope_id=project_id,
            complete_absent_batch=lambda request: work_item_service.complete_absent_batch(
                project_id=project_id, request=request
            ),
            upsert_work_item=lambda work_item: (
                work_item_service.upsert_work_item(
                    project_id=project_id,
                    work_item=work_item,
                    state_merge=merge_remediation_work_item_state,
                ).work_item
            ),
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
    config.require_gitlab_config(reason="GitLab work-item remediation control plane")
    if gitlab_work_item_service is None or gitlab_project_id is None:
        return NoOpRemediationControlPlane()
    return GitLabRemediationControlPlane(
        work_item_service=gitlab_work_item_service,
        project_id=gitlab_project_id,
    )
