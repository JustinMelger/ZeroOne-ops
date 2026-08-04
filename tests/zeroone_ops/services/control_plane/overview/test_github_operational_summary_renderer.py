from datetime import UTC, datetime

from zeroone_ops.services.control_plane.overview.github_operational_summary_renderer import (
    GitHubFindingSyncObservation,
    GitHubOperationalSummaryEntry,
    GitHubOperationalSummaryRenderer,
    GitHubOperationalSummaryView,
)


def test_render_summary_shows_read_only_operational_view() -> None:
    body = GitHubOperationalSummaryRenderer().render(
        GitHubOperationalSummaryView(
            policy_issue_url="https://github.example.com/octo-org/octo-repo/issues/1",
            work_item_counts={"approved": 2, "in_progress": 1, "blocked": 1},
            active_change_requests=[
                GitHubOperationalSummaryEntry(
                    title="ZeroOne Ops: E712 in service.py",
                    web_url="https://github.example.com/octo-org/octo-repo/issues/2",
                    status="in_progress",
                )
            ],
            recent_outcomes=[
                GitHubOperationalSummaryEntry(
                    title="ZeroOne Ops: C416 in helpers.py",
                    web_url="https://github.example.com/octo-org/octo-repo/issues/3",
                    status="completed",
                )
            ],
            latest_finding_sync=GitHubFindingSyncObservation(
                observed_at=datetime(2026, 8, 4, 10, 30, tzinfo=UTC),
                total_findings=5,
                promoted_findings=2,
                backlog_only_findings=3,
                severity_counts={"high": 2, "medium": 3},
                backlog_reason_counts={"severity_disabled": 3},
            ),
        )
    )

    assert "Work-item issues and the policy issue remain authoritative." in body
    assert "- Candidate: `0`" in body
    assert "- Ready: `2`" in body
    assert "- In progress: `1`" in body
    assert "- Blocked: `1`" in body
    assert "## Active Remediation PRs" in body
    assert "[ZeroOne Ops: E712 in service.py]" in body
    assert "- Findings: `5`" in body
    assert "- Backlog only: `3`" in body
    assert "`high`: 2, `medium`: 3" in body
    assert "## Recent Outcomes" in body
    assert "[ZeroOne Ops: C416 in helpers.py]" in body
    assert "[Open the ZeroOne Ops policy issue]" in body


def test_render_summary_escapes_untrusted_entry_text_and_drops_invalid_links() -> None:
    body = GitHubOperationalSummaryRenderer().render(
        GitHubOperationalSummaryView(
            policy_issue_url=None,
            work_item_counts={},
            active_change_requests=[
                GitHubOperationalSummaryEntry(
                    title="item](https://example.com/injected)\nnext",
                    web_url="https://example.com/valid",
                    status="in_progress`\nextra",
                ),
                GitHubOperationalSummaryEntry(
                    title="unsafe destination",
                    web_url="javascript:alert(1)",
                    status="blocked",
                ),
            ],
            recent_outcomes=[],
            latest_finding_sync=None,
        )
    )

    assert "[item\\](https://example.com/injected) next](<https://example.com/valid>)" in body
    assert "`in_progress' extra`" in body
    assert "- unsafe destination - `blocked`" in body
    assert "javascript:alert" not in body


def test_render_summary_drops_invalid_policy_link_destination() -> None:
    body = GitHubOperationalSummaryRenderer().render(
        GitHubOperationalSummaryView(
            policy_issue_url="javascript:alert(1)",
            work_item_counts={},
            active_change_requests=[],
            recent_outcomes=[],
            latest_finding_sync=None,
        )
    )

    assert "No policy issue link is available yet." in body
    assert "javascript:alert" not in body
