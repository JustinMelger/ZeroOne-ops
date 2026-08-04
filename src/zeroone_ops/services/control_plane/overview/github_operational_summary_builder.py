"""Build derived GitHub operational summary views from work-item state."""

from __future__ import annotations

from zeroone_ops.services.control_plane.overview.github_operational_summary_renderer import (
    GitHubFindingSyncObservation,
    GitHubOperationalSummaryEntry,
    GitHubOperationalSummaryView,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)


class GitHubOperationalSummaryBuilder:
    """Build a read-only summary view from authoritative work-item records."""

    _ACTIVE_CHANGE_REQUEST_LIMIT = 10
    _RECENT_OUTCOME_STATUSES = {"blocked", "completed", "dismissed"}

    def build(
        self,
        *,
        work_items: list[GitHubWorkItemLookupResult],
        policy_issue_url: str | None,
        latest_finding_sync: GitHubFindingSyncObservation | None,
        recent_outcome_limit: int = 5,
    ) -> GitHubOperationalSummaryView:
        """Return one derived summary view from open and closed work-item records."""
        counts = {status: 0 for status in ("candidate", "approved", "in_progress", "blocked")}
        active_change_requests: list[GitHubOperationalSummaryEntry] = []
        recent_outcomes: list[GitHubOperationalSummaryEntry] = []
        for result in work_items:
            work_item = result.work_item
            if result.is_open and work_item.status in counts:
                counts[work_item.status] += 1
            entry = GitHubOperationalSummaryEntry(
                title=result.issue.title,
                web_url=result.issue.web_url,
                status=work_item.status,
                updated_at=result.issue.updated_at,
            )
            if (
                result.is_open
                and work_item.status == "in_progress"
                and work_item.linked_change_request is not None
            ):
                active_change_requests.append(
                    GitHubOperationalSummaryEntry(
                        title=result.issue.title,
                        web_url=work_item.linked_change_request.web_url,
                        status=work_item.status,
                        updated_at=result.issue.updated_at,
                    )
                )
            if work_item.status in self._RECENT_OUTCOME_STATUSES:
                recent_outcomes.append(entry)
        recent_outcomes.sort(key=_outcome_updated_at, reverse=True)
        active_change_requests.sort(key=_outcome_updated_at, reverse=True)
        return GitHubOperationalSummaryView(
            policy_issue_url=policy_issue_url,
            work_item_counts=counts,
            active_change_requests=active_change_requests[: self._ACTIVE_CHANGE_REQUEST_LIMIT],
            active_change_requests_omitted_count=max(
                len(active_change_requests) - self._ACTIVE_CHANGE_REQUEST_LIMIT,
                0,
            ),
            recent_outcomes=recent_outcomes[:recent_outcome_limit],
            latest_finding_sync=latest_finding_sync,
        )


def _outcome_updated_at(entry: GitHubOperationalSummaryEntry) -> float:
    """Return a stable outcome sort key, with unknown timestamps ordered last."""
    if entry.updated_at is None or entry.updated_at.tzinfo is None:
        return float("-inf")
    return entry.updated_at.timestamp()
