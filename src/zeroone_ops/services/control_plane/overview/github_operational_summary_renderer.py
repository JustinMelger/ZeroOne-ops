"""Render GitHub operational summaries through the shared overview contract."""

from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    GITHUB_OPERATIONAL_SUMMARY_VOCABULARY,
    FindingSyncObservation,
    OperationalSummaryEntry,
    OperationalSummaryView,
)
from zeroone_ops.services.control_plane.overview.operational_summary_renderer import (
    OperationalSummaryRenderer,
)

GitHubFindingSyncObservation = FindingSyncObservation
GitHubOperationalSummaryEntry = OperationalSummaryEntry
GitHubOperationalSummaryView = OperationalSummaryView


class GitHubOperationalSummaryRenderer(OperationalSummaryRenderer):
    """Render the unchanged GitHub wording over the shared summary contract."""

    def __init__(self) -> None:
        """Initialize the GitHub vocabulary adapter."""
        super().__init__(vocabulary=GITHUB_OPERATIONAL_SUMMARY_VOCABULARY)
