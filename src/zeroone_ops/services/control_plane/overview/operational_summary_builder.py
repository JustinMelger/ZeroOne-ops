"""Build provider-neutral derived operational-summary views."""

from __future__ import annotations

from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    FindingSyncObservation,
    OperationalSummaryEntry,
    OperationalSummaryView,
    OperationalSummaryWorkItem,
)


class OperationalSummaryBuilder:
    """Build a read-only summary view from normalized work-item records."""

    _ACTIVE_CHANGE_REQUEST_LIMIT = 10
    _RECENT_OUTCOME_STATUSES = {"blocked", "completed", "dismissed"}

    def build(
        self,
        *,
        work_items: list[OperationalSummaryWorkItem],
        policy_issue_url: str | None,
        latest_finding_sync: FindingSyncObservation | None,
        recent_outcome_limit: int = 5,
    ) -> OperationalSummaryView:
        """Return one derived summary view from open and closed work-item records."""
        counts = {
            status: 0
            for status in ("candidate", "approved", "in_progress", "blocked", "capacity_deferred")
        }
        active_change_requests: list[OperationalSummaryEntry] = []
        recent_outcomes: list[OperationalSummaryEntry] = []
        for work_item in work_items:
            if work_item.status == "capacity_deferred":
                counts[work_item.status] += 1
            elif work_item.is_open and work_item.status in counts:
                counts[work_item.status] += 1
            entry = OperationalSummaryEntry(
                title=work_item.title,
                web_url=work_item.web_url,
                status=work_item.status,
                updated_at=work_item.updated_at,
            )
            if (
                work_item.is_open
                and work_item.status == "in_progress"
                and work_item.linked_change_request_url is not None
            ):
                active_change_requests.append(
                    OperationalSummaryEntry(
                        title=work_item.title,
                        web_url=work_item.linked_change_request_url,
                        status=work_item.status,
                        updated_at=work_item.updated_at,
                    )
                )
            if work_item.status in self._RECENT_OUTCOME_STATUSES:
                recent_outcomes.append(entry)
        recent_outcomes.sort(key=_outcome_updated_at, reverse=True)
        active_change_requests.sort(key=_outcome_updated_at, reverse=True)
        return OperationalSummaryView(
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


def _outcome_updated_at(entry: OperationalSummaryEntry) -> float:
    """Return a stable outcome sort key, with unknown timestamps ordered last."""
    if entry.updated_at is None or entry.updated_at.tzinfo is None:
        return float("-inf")
    return entry.updated_at.timestamp()
