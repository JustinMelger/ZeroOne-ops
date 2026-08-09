"""Parse GitHub operational-summary derived state through the shared contract."""

from zeroone_ops.services.control_plane.overview.operational_summary_parser import (
    OperationalSummaryParser,
)


class GitHubOperationalSummaryParser(OperationalSummaryParser):
    """Retain the GitHub parser name while sharing its persisted-state contract."""
