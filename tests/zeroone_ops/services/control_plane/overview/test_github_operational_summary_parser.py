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
        policy_deferred_count=1,
        policy_reactivated_count=2,
        no_longer_detected_count=3,
        projection_warning_count=4,
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


def test_parser_defaults_missing_policy_transition_counts_for_legacy_observations() -> None:
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
        '    "severity_counts": {"high": 1},\n'
        '    "backlog_reason_counts": {}\n'
        "  }\n"
        "}\n"
        "```\n\n"
        "</details>\n"
    )

    parsed = GitHubOperationalSummaryParser().parse_latest_finding_sync(body)

    assert parsed is not None
    assert parsed.policy_deferred_count == 0
    assert parsed.policy_reactivated_count == 0
    assert parsed.no_longer_detected_count == 0
    assert parsed.projection_warning_count == 0


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


def test_parser_rejects_inconsistent_finding_totals() -> None:
    body = (
        "<details>\n"
        "<summary><code>zeroone-operational-summary-state</code> derived state</summary>\n\n"
        "```json\n"
        "{\n"
        '  "latest_finding_sync": {\n'
        '    "observed_at": "2026-08-04T10:30:00+00:00",\n'
        '    "total_findings": 3,\n'
        '    "promoted_findings": 1,\n'
        '    "backlog_only_findings": 1,\n'
        '    "severity_counts": {"high": 2},\n'
        '    "backlog_reason_counts": {}\n'
        "  }\n"
        "}\n"
        "```\n\n"
        "</details>\n"
    )

    assert GitHubOperationalSummaryParser().parse_latest_finding_sync(body) is None
