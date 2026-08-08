"""GitHub-local composition for shared work-item lifecycle reconciliation."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import httpx

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.work_item_lifecycle_service import (
    WorkItemLifecycleResult,
    WorkItemLifecycleService,
)

GitHubWorkItemLifecycleResult = WorkItemLifecycleResult


class GitHubChangeRequestStateClient(Protocol):
    """Structural interface implemented by the GitHub change-request client."""

    def get_change_request_state(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> ChangeRequestState:
        """Return current state for one GitHub pull request."""
        raise NotImplementedError


class GitHubWorkItemLifecycleService:
    """Compose shared lifecycle reconciliation with GitHub work-item transport."""

    def __init__(
        self,
        *,
        work_item_service: GitHubWorkItemService,
        change_request_client: GitHubChangeRequestStateClient,
    ) -> None:
        """Initialize GitHub lifecycle composition."""
        self.work_item_service = work_item_service
        self.change_request_client = change_request_client

    def reconcile(
        self,
        *,
        repository_id: str,
        now: datetime,
        persist: bool = True,
    ) -> GitHubWorkItemLifecycleResult:
        """Reconcile GitHub work items for one repository."""
        return WorkItemLifecycleService(
            provider_name="GitHub",
            list_open_work_items=lambda: [
                (result.issue.number, result.work_item)
                for result in self.work_item_service.list_open_work_items(
                    repository_id=repository_id
                )
            ],
            upsert_work_item=lambda work_item: (
                self.work_item_service.upsert_work_item(
                    repository_id=repository_id,
                    work_item=work_item,
                ).issue.number
            ),
            close_work_item_issue=lambda issue_number: self.work_item_service.close_work_item_issue(
                repository_id=repository_id,
                issue_number=issue_number,
            ),
            get_change_request_state=lambda change_request_number: (
                self.change_request_client.get_change_request_state(
                    repository_id=repository_id,
                    change_request_number=change_request_number,
                )
            ),
            recoverable_errors=(GitHubClientError, httpx.HTTPError),
        ).reconcile(now=now, persist=persist)
