"""Build GitLab operational summary views through the shared overview contract."""

from zeroone_ops.services.control_plane.overview.operational_summary_builder import (
    OperationalSummaryBuilder,
)
from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    FindingSyncObservation,
    OperationalSummaryView,
    OperationalSummaryWorkItem,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)


class GitLabOperationalSummaryBuilder:
    """Adapt GitLab work-item lookup results to the shared summary builder."""

    def __init__(self, builder: OperationalSummaryBuilder | None = None) -> None:
        """Initialize the GitLab work-item normalization adapter."""
        self.builder = builder or OperationalSummaryBuilder()

    def build(
        self,
        *,
        work_items: list[GitLabWorkItemLookupResult],
        policy_issue_url: str | None,
        latest_finding_sync: FindingSyncObservation | None,
        recent_outcome_limit: int = 5,
    ) -> OperationalSummaryView:
        """Build a GitLab summary view from normalized work items."""
        return self.builder.build(
            work_items=[_normalize_work_item(result) for result in work_items],
            policy_issue_url=policy_issue_url,
            latest_finding_sync=latest_finding_sync,
            recent_outcome_limit=recent_outcome_limit,
        )


def _normalize_work_item(result: GitLabWorkItemLookupResult) -> OperationalSummaryWorkItem:
    """Normalize one GitLab lookup result without leaking it into the shared core."""
    work_item = result.work_item
    return OperationalSummaryWorkItem(
        title=result.issue.title,
        web_url=result.issue.web_url,
        status=work_item.status,
        is_open=result.is_open,
        updated_at=result.issue.updated_at,
        linked_change_request_url=(
            work_item.linked_change_request.web_url
            if work_item.linked_change_request is not None
            else None
        ),
    )
