from datetime import UTC, datetime

from zeroone_ops.services.control_plane.overview.github_operational_summary_parser import (
    GitHubOperationalSummaryParser,
)
from zeroone_ops.services.control_plane.overview.github_operational_summary_renderer import (
    GitHubFindingSyncObservation,
    GitHubOperationalSummaryRenderer,
    GitHubOperationalSummaryView,
)


def test_parser_reads_persisted_finding_sync_observation() -> None:
    observation = GitHubFindingSyncObservation(
        observed_at=datetime(2026, 8, 4, 10, 30, tzinfo=UTC),
        total_findings=5,
        promoted_findings=2,
        backlog_only_findings=3,
        severity_counts={"high": 2, "medium": 3},
        backlog_reason_counts={"severity_disabled": 3},
    )
    body = GitHubOperationalSummaryRenderer().render(
        GitHubOperationalSummaryView(
            policy_issue_url=None,
            work_item_counts={},
            active_change_requests=[],
            recent_outcomes=[],
            latest_finding_sync=observation,
        )
    )

    parsed = GitHubOperationalSummaryParser().parse_latest_finding_sync(body)

    assert parsed == observation


def test_parser_ignores_malformed_derived_state() -> None:
    body = (
        "<details>\n"
        "<summary><code>zeroone-operational-summary-state</code> derived state</summary>\n\n"
        "```json\n"
        "{not-json}\n"
        "```\n\n"
        "</details>\n"
    )

    assert GitHubOperationalSummaryParser().parse_latest_finding_sync(body) is None


def test_parser_rejects_unbounded_or_negative_aggregate_counts() -> None:
    body = (
        "<details>\n"
        "<summary><code>zeroone-operational-summary-state</code> derived state</summary>\n\n"
        "```json\n"
        "{\n"
        '  "latest_finding_sync": {\n'
        '    "observed_at": "2026-08-04T10:30:00+00:00",\n'
        '    "total_findings": 1,\n'
        '    "promoted_findings": 1,\n'
        '    "backlog_only_findings": 0,\n'
        '    "severity_counts": {"high": -1},\n'
        '    "backlog_reason_counts": {}\n'
        "  }\n"
        "}\n"
        "```\n\n"
        "</details>\n"
    )

    assert GitHubOperationalSummaryParser().parse_latest_finding_sync(body) is None


def test_parser_rejects_negative_or_boolean_top_level_counts() -> None:
    body = (
        "<details>\n"
        "<summary><code>zeroone-operational-summary-state</code> derived state</summary>\n\n"
        "```json\n"
        "{\n"
        '  "latest_finding_sync": {\n'
        '    "observed_at": "2026-08-04T10:30:00+00:00",\n'
        '    "total_findings": true,\n'
        '    "promoted_findings": -1,\n'
        '    "backlog_only_findings": 0,\n'
        '    "severity_counts": {},\n'
        '    "backlog_reason_counts": {}\n'
        "  }\n"
        "}\n"
        "```\n\n"
        "</details>\n"
    )

    assert GitHubOperationalSummaryParser().parse_latest_finding_sync(body) is None
