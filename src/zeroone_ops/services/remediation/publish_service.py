"""Publish service.

This module owns branch push and provider-backed change-request publication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import (
    RemediationExecutionTarget,
    remediation_profile_for,
)
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    WorkItemSourceRef,
    WorkItemState,
    WorkItemStatus,
)
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.github_work_item_client import GitHubWorkItemClient
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.control_plane.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.remediation.change_request_publisher import (
    ChangeRequestPublishRequest,
    RemediationChangeRequestPublisher,
    build_remediation_change_request_publisher,
)
from zeroone_ops.services.shared.branch_manager import (
    BranchManager,
    BranchManagerError,
)
from zeroone_ops.settings import load_github_connection_config

LOGGER = logging.getLogger(__name__)


@dataclass
class PublishResult:
    """Summarize remote publish and change-request creation."""

    branch_name: str | None = None
    change_request_url: str | None = None
    change_request_action: str | None = None
    error_message: str | None = None


class PublishService:
    """Push branches and create or reuse provider-backed change requests.

    Args:
        config: Loaded application configuration.
        branch_manager: Branch manager implementation.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        branch_manager: BranchManager,
        change_request_publisher: RemediationChangeRequestPublisher | None = None,
        github_work_item_service: GitHubWorkItemService | None = None,
        github_repository_id: str | None = None,
    ) -> None:
        """Initialize the publish service.

        Args:
            config: Loaded application configuration.
            branch_manager: Branch manager implementation.
            change_request_publisher: Optional provider-local publisher override.
            github_work_item_service: Optional GitHub work-item service override.
            github_repository_id: Optional GitHub repository ID override for tests.
        """
        self.config = config
        self.branch_manager = branch_manager
        self.change_request_publisher = change_request_publisher
        self.github_work_item_service = github_work_item_service
        self.github_repository_id = github_repository_id

    def publish(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        change_request_title: str | None = None,
        change_request_description: str | None = None,
    ) -> PublishResult:
        """Push the current branch and create or reuse a change request."""
        if change_request_title is None:
            return PublishResult(error_message="Publish failed: change request title is required.")
        if change_request_description is None:
            return PublishResult(
                error_message="Publish failed: change request description is required."
            )
        github_work_item: WorkItemState | None = None
        try:
            labels, assignee_username = self._publication_options()
            target_branch = self.config.require_remediation_target_branch(
                reason="Remediation publish",
            )
            publisher = self.change_request_publisher or build_remediation_change_request_publisher(
                self.config
            )
            github_work_item = self._upsert_github_work_item(
                selected_issue=selected_issue,
                status="in_progress",
                linked_change_request=None,
            )
            pushed_branch = self.branch_manager.push_current_branch()
            published_change_request = publisher.publish(
                ChangeRequestPublishRequest(
                    source_branch=pushed_branch,
                    target_branch=target_branch,
                    title=self.build_change_request_title(
                        selected_issue=selected_issue,
                        proposed_title=change_request_title,
                    ),
                    description=self.build_change_request_description(
                        selected_issue=selected_issue,
                        change_summary=change_request_description,
                    ),
                    labels=labels,
                    assignee_username=assignee_username,
                )
            )
            self._sync_github_work_item_change_request_link(
                selected_issue=selected_issue,
                published_change_request=published_change_request.info,
                existing_work_item=github_work_item,
            )
        except (BranchManagerError, GitLabClientError, GitHubClientError, RuntimeError) as error:
            self._mark_github_work_item_blocked_after_failure(
                selected_issue=selected_issue,
                existing_work_item=github_work_item,
            )
            return PublishResult(error_message=f"Publish failed: {error}")
        return PublishResult(
            branch_name=pushed_branch,
            change_request_url=published_change_request.info.web_url,
            change_request_action=published_change_request.action,
        )

    def build_change_request_title(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        proposed_title: str,
    ) -> str:
        """Build a conventional-commit-style change-request title.

        Args:
            selected_issue: Selected remediation execution target.
            proposed_title: LLM-proposed change-request title.

        Returns:
            A deterministic conventional-commit-style title.
        """
        del proposed_title
        issue_summary = selected_issue.rule_id or selected_issue.source_ref
        file_name = Path(selected_issue.file_path).name
        return f"fix: remediate {issue_summary} in {file_name}"

    def build_change_request_description(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        change_summary: str,
    ) -> str:
        """Build a deterministic change-request description."""
        profile = remediation_profile_for(selected_issue)
        issue_line = str(selected_issue.line) if selected_issue.line is not None else "n/a"
        return "\n".join(
            [
                "## Summary",
                change_summary,
                "",
                f"## {profile.mr_section_title}",
                f"- Source: `{profile.source_display_name}`",
                f"- {profile.item_reference_label}: `{selected_issue.source_ref}`",
                f"- Rule: `{selected_issue.rule_id or 'unknown'}`",
                f"- Severity: `{selected_issue.severity or 'unknown'}`",
                f"- Type: `{selected_issue.issue_type or selected_issue.source_type}`",
                f"- File: `{selected_issue.file_path}`",
                f"- Line: `{issue_line}`",
                f"- Message: {selected_issue.message}",
                "",
                "## Notes",
                profile.diff_note,
            ]
        )

    def _publication_options(self) -> tuple[list[str], str | None]:
        """Return provider-local publish options for the current repository config."""
        if self.config.platform == "gitlab":
            workflow_gitlab_config = self.config.require_gitlab_config(
                reason="Remediation publish",
            )
            return (
                workflow_gitlab_config.labels,
                workflow_gitlab_config.merge_request_assignee_username,
            )
        if self.config.platform == "github":
            workflow_github_config = self.config.github
            if workflow_github_config is None:
                return ([], None)
            return (
                workflow_github_config.labels,
                workflow_github_config.pull_request_assignee_username,
            )
        return ([], None)

    def _upsert_github_work_item(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        status: str,
        linked_change_request: ChangeRequestInfo | ChangeRequestRef | None,
        existing_work_item: WorkItemState | None = None,
    ) -> WorkItemState | None:
        """Create or update the authoritative GitHub work-item issue when on GitHub."""
        if self.config.platform != "github":
            return None
        repository_id = self._github_repository_id()
        service = self.github_work_item_service or GitHubWorkItemService(
            GitHubWorkItemClient(load_github_connection_config())
        )
        work_item = self._build_github_work_item(
            selected_issue=selected_issue,
            status=cast(WorkItemStatus, status),
            repository_scope=repository_id,
            linked_change_request=linked_change_request,
            existing_work_item=existing_work_item,
        )
        return service.upsert_work_item(
            repository_id=repository_id,
            work_item=work_item,
        ).work_item

    def _build_github_work_item(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        status: WorkItemStatus,
        repository_scope: str,
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
                repository_scope=repository_scope,
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

    def _github_repository_id(self) -> str:
        """Return the GitHub repository ID for work-item publication."""
        if self.github_repository_id is not None:
            return self.github_repository_id
        return load_github_connection_config().repository

    def _mark_github_work_item_blocked_after_failure(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Best-effort transition of GitHub work-item state after publish failure."""
        if existing_work_item is None:
            return
        try:
            self._upsert_github_work_item(
                selected_issue=selected_issue,
                status="blocked",
                linked_change_request=existing_work_item.linked_change_request,
                existing_work_item=existing_work_item,
            )
        except (GitHubClientError, RuntimeError):
            return

    def _sync_github_work_item_change_request_link(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        published_change_request: ChangeRequestInfo,
        existing_work_item: WorkItemState | None,
    ) -> None:
        """Best-effort sync of the linked change request onto GitHub work-item state."""
        try:
            self._upsert_github_work_item(
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
