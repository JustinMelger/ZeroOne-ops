"""Provider-local remediation control-plane adapters."""

from __future__ import annotations

import logging
from typing import Protocol, cast
from uuid import uuid4

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    WorkItemSourceRef,
    WorkItemState,
    WorkItemStatus,
)
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.services.control_plane.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.settings import load_github_connection_config

LOGGER = logging.getLogger(__name__)


class RemediationControlPlane(Protocol):
    """Project remediation publish lifecycle into the provider-local control plane."""

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
    ) -> WorkItemState | None:
        """Record that remediation publish has started."""

    def mark_publish_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
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

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
    ) -> WorkItemState | None:
        """Ignore publish-start projection when no control plane is active."""
        del selected_issue
        return None

    def mark_publish_blocked(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Ignore blocked-state projection when no control plane is active."""
        del selected_issue, existing_work_item

    def sync_change_request_link(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        published_change_request: ChangeRequestInfo,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Ignore change-request link projection when no control plane is active."""
        del selected_issue, published_change_request, existing_work_item


class GitHubRemediationControlPlane:
    """Project remediation publish lifecycle onto authoritative GitHub work items."""

    def __init__(
        self,
        *,
        work_item_service: GitHubWorkItemService,
        repository_id: str,
    ) -> None:
        """Initialize the GitHub remediation control-plane adapter."""
        self.work_item_service = work_item_service
        self.repository_id = repository_id

    def mark_publish_started(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
    ) -> WorkItemState:
        """Create or update the authoritative GitHub work item as in progress."""
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
    ) -> None:
        """Best-effort transition of GitHub work-item state after publish failure."""
        if existing_work_item is None:
            return
        try:
            self._upsert_work_item(
                selected_issue=selected_issue,
                status="blocked",
                linked_change_request=existing_work_item.linked_change_request,
                existing_work_item=existing_work_item,
            )
        except (GitHubClientError, RuntimeError):
            return

    def sync_change_request_link(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        published_change_request: ChangeRequestInfo,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Best-effort sync of the linked change request onto GitHub work-item state."""
        try:
            self._upsert_work_item(
                selected_issue=selected_issue,
                status="in_progress",
                linked_change_request=published_change_request,
                existing_work_item=existing_work_item,
            )
        except (GitHubClientError, RuntimeError):
            LOGGER.warning(
                "GitHub work-item linkage sync failed after change-request publication",
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
    ) -> WorkItemState:
        """Create or update the authoritative GitHub work-item issue."""
        work_item = self._build_work_item(
            selected_issue=selected_issue,
            status=cast(WorkItemStatus, status),
            linked_change_request=linked_change_request,
            existing_work_item=existing_work_item,
        )
        return self.work_item_service.upsert_work_item(
            repository_id=self.repository_id,
            work_item=work_item,
        ).work_item

    def _build_work_item(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        status: WorkItemStatus,
        linked_change_request: ChangeRequestInfo | ChangeRequestRef | None,
        existing_work_item: WorkItemState | None,
    ) -> WorkItemState:
        """Build the canonical GitHub work-item state for remediation publication."""
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
                repository_scope=self.repository_id,
            ),
            summary=selected_issue.title,
            severity=selected_issue.severity,
            file_path=selected_issue.file_path,
            line=selected_issue.line,
            linked_change_request=(
                None
                if linked_change_request is None
                else self._normalize_change_request_ref(linked_change_request)
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


def build_remediation_control_plane(
    config: AppConfig,
    *,
    github_work_item_service: GitHubWorkItemService | None = None,
    github_repository_id: str | None = None,
) -> RemediationControlPlane:
    """Build the provider-local remediation control-plane adapter for one repo config."""
    if config.platform != "github":
        return NoOpRemediationControlPlane()
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
