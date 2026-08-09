"""Render GitLab operational summaries through the shared overview contract."""

from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    GITLAB_OPERATIONAL_SUMMARY_VOCABULARY,
)
from zeroone_ops.services.control_plane.overview.operational_summary_renderer import (
    OperationalSummaryRenderer,
)


class GitLabOperationalSummaryRenderer(OperationalSummaryRenderer):
    """Render GitLab merge-request wording over the shared summary contract."""

    def __init__(self) -> None:
        """Initialize the GitLab vocabulary adapter."""
        super().__init__(vocabulary=GITLAB_OPERATIONAL_SUMMARY_VOCABULARY)
