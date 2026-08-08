"""GitLab-local composition for shared work-item lifecycle reconciliation."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

import httpx

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_service import (
    GitLabWorkItemService,
)
from zeroone_ops.services.control_plane.work_items.work_item_lifecycle_service import (
    WorkItemLifecycleResult,
    WorkItemLifecycleService,
)

GitLabWorkItemLifecycleResult = WorkItemLifecycleResult


class GitLabChangeRequestStateClient(Protocol):
    """Structural interface implemented by the GitLab review client."""

    def get_change_request_state(
        self,
        *,
        project_id: str,
        change_request_number: int,
    ) -> ChangeRequestState:
        """Return current state for one GitLab merge request."""
        raise NotImplementedError


class GitLabWorkItemLifecycleService:
    """Compose shared lifecycle reconciliation with GitLab work-item transport."""

    def __init__(
        self,
        *,
        work_item_service: GitLabWorkItemService,
        change_request_client: GitLabChangeRequestStateClient,
    ) -> None:
        """Initialize GitLab lifecycle composition."""
        self.work_item_service = work_item_service
        self.change_request_client = change_request_client

    def reconcile(
        self,
        *,
        project_id: str,
        now: datetime,
        persist: bool = True,
    ) -> GitLabWorkItemLifecycleResult:
        """Reconcile GitLab work items for one project."""
        return WorkItemLifecycleService(
            provider_name="GitLab",
            list_open_work_items=lambda: [
                (result.issue.iid, result.work_item)
                for result in self.work_item_service.list_open_work_items(project_id=project_id)
            ],
            upsert_work_item=lambda work_item: (
                self.work_item_service.upsert_work_item(
                    project_id=project_id,
                    work_item=work_item,
                ).issue.iid
            ),
            close_work_item_issue=lambda issue_iid: self.work_item_service.close_work_item_issue(
                project_id=project_id,
                issue_iid=issue_iid,
            ),
            get_change_request_state=lambda change_request_number: (
                self.change_request_client.get_change_request_state(
                    project_id=project_id,
                    change_request_number=change_request_number,
                )
            ),
            recoverable_errors=(GitLabClientError, httpx.HTTPError),
        ).reconcile(now=now, persist=persist)
