"""Backward-compatible GitHub adapter for shared work-item reconciliation."""

from zeroone_ops.services.control_plane.work_items import (
    work_item_change_request_reconciliation_service as reconciliation,
)

ClosedUnmergedWorkItemOutcome = reconciliation.ClosedUnmergedWorkItemOutcome
GitHubWorkItemReconciliationResult = reconciliation.WorkItemChangeRequestReconciliationResult


class GitHubWorkItemReconciliationService(
    reconciliation.WorkItemChangeRequestReconciliationService
):
    """Retain the GitHub import surface while using the neutral decision logic."""
