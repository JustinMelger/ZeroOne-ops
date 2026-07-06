from datetime import UTC, datetime
from pathlib import Path

from zeroone_ops.models.dashboard import (
    DashboardItem,
    DashboardPolicyState,
    DashboardSection,
    DashboardSeverityPolicyStateEntry,
)
from zeroone_ops.services.dashboard.dashboard_parser import (
    DashboardParseError,
    DashboardParser,
)
from zeroone_ops.services.dashboard.dashboard_renderer import DashboardRenderer

FIXTURES_DIR = Path(__file__).with_name("fixtures")


def build_item(*, item_id: str, status: str = "open") -> DashboardItem:
    return DashboardItem(
        id=item_id,
        source="sonarqube",
        type="code_smell_fix",
        status=status,
        title="Simplify boolean comparison",
        summary="Replace explicit boolean equality with direct truthiness.",
        priority="low",
        source_reference="issue-1",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        source_severity="LOW",
        automation_severity="low",
        validation_commands=["uv run pytest"],
    )


def empty_change_requests_opened_section() -> DashboardSection:
    return DashboardSection(
        key="change_requests_opened",
        title="Change Requests Opened",
        items=[],
    )


def empty_change_request_reviews_section() -> DashboardSection:
    return DashboardSection(
        key="change_request_reviews",
        title="Change Request Reviews",
        items=[],
    )


def test_parse_round_trips_rendered_dashboard_body() -> None:
    renderer = DashboardRenderer()
    parser = DashboardParser()
    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[build_item(item_id="sonar:1")],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            empty_change_requests_opened_section(),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(
                key="rejected_or_ignored",
                title="Rejected Or Ignored",
                items=[],
            ),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert document.sections[0].items[0].id == "sonar:1"
    assert document.sections[0].items[0].rule == "python:S1125"


def test_parse_round_trips_dashboard_item_datetime_metadata() -> None:
    renderer = DashboardRenderer()
    parser = DashboardParser()
    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="in_progress",
                title="In Progress",
                items=[
                    build_item(item_id="sonar:1", status="in_progress").model_copy(
                        update={
                            "last_run_id": "run-1",
                            "status_updated_at": datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
                        }
                    )
                ],
            ),
            DashboardSection(key="open_candidates", title="Open Candidates", items=[]),
            empty_change_requests_opened_section(),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(
                key="rejected_or_ignored",
                title="Rejected Or Ignored",
                items=[],
            ),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    item = document.items_by_id()["sonar:1"]
    assert item.last_run_id == "run-1"
    assert item.status_updated_at == datetime(2026, 4, 7, 12, 0, tzinfo=UTC)


def test_rendered_dashboard_body_includes_human_readable_summary_table() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[build_item(item_id="sonar:1")],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            empty_change_requests_opened_section(),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(
                key="rejected_or_ignored",
                title="Rejected Or Ignored",
                items=[],
            ),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "### Overview" in body
    assert "| Open | In progress | Change requests opened | Failed | Done |" in body
    assert "| 1 | 0 | 0 | 0 | 0 |" in body
    assert "### Queue Auto-fix" in body
    assert "### Needs Review" in body
    assert "| Item | Area | File | Priority | Next Step | Summary |" in body
    assert "`sonar:1`" in body
    assert "`service.py`" in body
    assert "Queue Auto-fix" in body
    assert "Simplify boolean comparison" in body
    assert "### In Flight" in body
    assert "### Completed" in body
    assert "### Dismissed" in body
    assert "### Work Type Breakdown" in body
    assert "zeroone-dashboard-manifest" in body
    assert "<details>" in body
    assert "<summary><code>sonar:1</code> details</summary>" in body


def test_rendered_dashboard_body_keeps_new_workflow_layout_when_empty() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(key="open_candidates", title="Open Candidates", items=[]),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            empty_change_requests_opened_section(),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(
                key="rejected_or_ignored",
                title="Rejected Or Ignored",
                items=[],
            ),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "## Open Candidates" in body
    assert "### Overview" in body
    assert "| Open | In progress | Change requests opened | Failed | Done |" in body
    assert "| 0 | 0 | 0 | 0 | 0 |" in body
    assert "### Queue Auto-fix" in body
    assert "### Needs Review" in body
    assert "### In Flight" in body
    assert "### Completed" in body
    assert "### Dismissed" in body
    assert "### Work Type Breakdown" in body
    assert "## In Progress" not in body
    assert "## Change Requests Opened" not in body
    assert "\n## Completed\n" not in body


def test_manual_review_rejection_stays_out_of_active_workflow_tables() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[
                    build_item(item_id="sonar:manual", status="rejected").model_copy(
                        update={
                            "log_excerpt": (
                                "Patch generation skipped because manual review is required."
                            )
                        }
                    )
                ],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            empty_change_requests_opened_section(),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(
                key="rejected_or_ignored",
                title="Rejected Or Ignored",
                items=[],
            ),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "<summary><code>sonar:manual</code> details</summary>" in body
    assert "### Dismissed" in body
    assert "⚪ Rejected" in body
    assert "Review Manually" not in body
    assert "manual review is required" in body


def test_rendered_review_section_uses_specialized_review_summary_layout() -> None:
    renderer = DashboardRenderer()
    review_item = DashboardItem(
        id="mr-review:363:abc123def456",
        source="pull_request_review",
        type="review_status",
        status="done",
        title="Review status for !363",
        summary="Global search now delegates license plate lookups differently.",
        priority="high",
        source_reference="https://gitlab.example.com/group/project/-/merge_requests/363",
        merge_request_iid=363,
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/363",
        reviewed_head_sha="abc123def456",
        review_status="findings_present",
        review_findings_count=3,
        review_feedback_summary="License logic change with visible redirect impact.",
    )

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="change_request_reviews",
                title="Change Request Reviews",
                items=[review_item],
            )
        ],
    )

    assert "### Overview" in body
    assert "| MRs | Needs attention | Findings total | High priority |" in body
    assert "| 1 | 1 | 3 | 1 |" in body
    assert "### Needs Attention" in body
    assert (
        "| MR | Passes | Outcome | Findings | Confidence | Priority | Summary | "
        "Reviewed SHA |" in body
    )
    assert "[!363](https://gitlab.example.com/group/project/-/merge_requests/363)" in body
    assert "⚠️ Findings present" in body
    assert (
        "| [!363](https://gitlab.example.com/group/project/-/merge_requests/363) | "
        "1 | ⚠️ Findings present | 3 | - | 🔴 High | "
        "License logic change with visible redirect impact. | `abc123de` |" in body
    )
    assert "License logic change with visible redirect impact." in body
    assert "### Review History" in body
    assert (
        "| MR | Passes | Outcome | Findings | Confidence | Priority | Summary | "
        "Reviewed SHA |" in body
    )
    assert "`abc123de`" in body


def test_rendered_review_section_groups_repeated_passes_by_merge_request() -> None:
    renderer = DashboardRenderer()
    review_items = [
        DashboardItem(
            id="mr-review:363:aaa111bbb222",
            source="pull_request_review",
            type="review_status",
            status="done",
            title="Review status for !363",
            summary="Earlier summary.",
            priority="high",
            source_reference="https://gitlab.example.com/group/project/-/merge_requests/363",
            merge_request_iid=363,
            merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/363",
            reviewed_head_sha="aaa111bbb222",
            review_status="findings_present",
            review_findings_count=2,
            review_feedback_summary="Earlier findings still present.",
            review_feedback_updated_at=datetime(2026, 5, 11, 8, 0, tzinfo=UTC),
        ),
        DashboardItem(
            id="mr-review:363:ccc333ddd444",
            source="pull_request_review",
            type="review_status",
            status="done",
            title="Review status for !363",
            summary="Latest summary.",
            priority="high",
            source_reference="https://gitlab.example.com/group/project/-/merge_requests/363",
            merge_request_iid=363,
            merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/363",
            reviewed_head_sha="ccc333ddd444",
            review_status="findings_present",
            review_findings_count=1,
            review_feedback_summary="Latest findings summary.",
            review_feedback_updated_at=datetime(2026, 5, 11, 9, 0, tzinfo=UTC),
        ),
    ]

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="change_request_reviews",
                title="Change Request Reviews",
                items=review_items,
            )
        ],
    )

    assert "| 1 | 1 | 1 | 1 |" in body
    assert "2 passes. Latest findings summary." in body
    assert body.count("[!363](https://gitlab.example.com/group/project/-/merge_requests/363)") >= 2
    assert (
        "| [!363](https://gitlab.example.com/group/project/-/merge_requests/363) | "
        "2 | ⚠️ Findings present | 1 | - | 🔴 High | "
        "2 passes. Latest findings summary. | `ccc333dd` |" in body
    )
    assert "<summary><code>mr-review:363:aaa111bbb222</code> details</summary>" in body
    assert "<summary><code>mr-review:363:ccc333ddd444</code> details</summary>" in body


def test_rendered_review_section_projects_linked_remediation_review_metadata() -> None:
    renderer = DashboardRenderer()
    remediation_review_item = build_item(
        item_id="sonar:reviewed", status="change_request_opened"
    ).model_copy(
        update={
            "change_request_number": 77,
            "change_request_url": "https://gitlab.example.com/group/project/-/merge_requests/77",
            "reviewed_head_sha": "def456ghi789",
            "review_status": "findings_present",
            "review_findings_count": 2,
            "review_feedback_summary": "Latest linked remediation review summary.",
            "review_feedback_updated_at": datetime(2026, 5, 12, 9, 30, tzinfo=UTC),
        }
    )

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="change_requests_opened",
                title="Change Requests Opened",
                items=[remediation_review_item],
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            DashboardSection(
                key="change_request_reviews",
                title="Change Request Reviews",
                items=[],
            ),
            DashboardSection(
                key="rejected_or_ignored",
                title="Rejected Or Ignored",
                items=[],
            ),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "| MRs | Needs attention | Findings total | High priority |" in body
    assert "| 1 | 1 | 2 | 0 |" in body
    assert "### Review History" in body
    assert "[!77](https://gitlab.example.com/group/project/-/merge_requests/77)" in body
    assert "Latest linked remediation review summary." in body
    assert "`def456gh`" in body


def test_rendered_review_section_prefers_status_updated_at_when_review_timestamp_missing() -> None:
    renderer = DashboardRenderer()
    review_items = [
        DashboardItem(
            id="mr-review:88:aaa111",
            source="pull_request_review",
            type="review_status",
            status="done",
            title="Review status for !88",
            summary="Older summary.",
            priority="low",
            source_reference="https://gitlab.example.com/group/project/-/merge_requests/88",
            merge_request_iid=88,
            merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/88",
            reviewed_head_sha="aaa111bbb222",
            review_status="findings_present",
            review_findings_count=2,
            review_feedback_summary="Older fallback summary.",
            status_updated_at=datetime(2026, 5, 11, 8, 0, tzinfo=UTC),
        ),
        DashboardItem(
            id="mr-review:88:ccc333",
            source="pull_request_review",
            type="review_status",
            status="done",
            title="Review status for !88",
            summary="Newer summary.",
            priority="low",
            source_reference="https://gitlab.example.com/group/project/-/merge_requests/88",
            merge_request_iid=88,
            merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/88",
            reviewed_head_sha="ccc333ddd444",
            review_status="findings_present",
            review_findings_count=1,
            review_feedback_summary="Newer fallback summary.",
            status_updated_at=datetime(2026, 5, 11, 9, 0, tzinfo=UTC),
        ),
    ]

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="change_request_reviews",
                title="Change Request Reviews",
                items=review_items,
            )
        ],
    )

    assert "2 passes. Newer fallback summary." in body
    assert "`ccc333dd`" in body


def test_rendered_dashboard_body_surfaces_failure_note_in_summary_table() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(key="open_candidates", title="Open Candidates", items=[]),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="change_requests_opened", title="Change Requests Opened", items=[]
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(
                key="recent_failures",
                title="Recent Failures",
                items=[
                    build_item(item_id="sonar:failed", status="failed").model_copy(
                        update={
                            "log_excerpt": ("Merge request metadata is inaccessible from GitLab.")
                        }
                    )
                ],
            ),
        ],
    )

    assert "| Item | Area | File | Priority | Next Step | Summary |" in body
    assert "Investigate Failure" in body
    assert "Investigate environment or tooling failure before rerun." in body
    assert "Merge request metadata is inaccessible from GitLab." in body


def test_rendered_dashboard_body_surfaces_retry_eligible_failure_guidance() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[
                    build_item(item_id="sonar:failed", status="failed").model_copy(
                        update={
                            "retry_eligible": True,
                            "log_excerpt": "GitLab token was expired during publish.",
                        }
                    )
                ],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="change_requests_opened", title="Change Requests Opened", items=[]
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "Retry Auto-fix" in body
    assert "Retry ready after fixing the blocker." in body
    assert "GitLab token was expired during publish." in body


def test_rendered_dashboard_body_surfaces_retry_blocked_failure_guidance() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[
                    build_item(item_id="sonar:failed", status="failed").model_copy(
                        update={
                            "retry_eligible": False,
                            "retry_block_reason": "Latest review outcome requires manual review.",
                            "log_excerpt": "Remediation merge request was closed without merge.",
                        }
                    )
                ],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="change_requests_opened", title="Change Requests Opened", items=[]
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "Review Retry Blocker" in body
    assert (
        "Blocked until review or policy changes: "
        "Latest review outcome requires manual review." in body
    )


def test_rendered_workflow_section_uses_specialized_workflow_summary_layout() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[build_item(item_id="sonar:open", status="open")],
            ),
            DashboardSection(
                key="in_progress",
                title="In Progress",
                items=[build_item(item_id="sonar:progress", status="in_progress")],
            ),
            DashboardSection(
                key="change_requests_opened",
                title="Change Requests Opened",
                items=[
                    build_item(item_id="sonar:mr", status="change_request_opened").model_copy(
                        update={
                            "merge_request_iid": 42,
                            "merge_request_url": (
                                "https://gitlab.example.com/group/project/-/merge_requests/42"
                            ),
                        }
                    )
                ],
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "### Overview" in body
    assert "| Open | In progress | Change requests opened | Failed | Done |" in body
    assert "| 1 | 1 | 1 | 0 | 0 |" in body
    assert "### Queue Auto-fix" in body
    assert "### Needs Review" in body
    assert "| Item | Area | File | Priority | Next Step | Summary |" in body
    assert "### In Flight" in body
    assert "| Item | Area | Status | Priority | Review Summary |" in body
    assert "### Completed" in body
    assert "### Work Type Breakdown" in body
    assert "`sonar:open`" in body
    assert "`sonar:progress`" in body
    assert "`sonar:mr`" in body
    assert "Queue Auto-fix" in body
    assert "📦 Change Request Opened" in body


def test_render_hides_legacy_empty_workflow_sections_when_combined_view_is_present() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[build_item(item_id="sonar:open", status="open")],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="change_requests_opened", title="Change Requests Opened", items=[]
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "## Open Candidates" in body
    assert "## In Progress" not in body
    assert "## Change Requests Opened" not in body
    assert "\n## Completed\n" not in body
    assert "## Rejected Or Ignored" not in body
    assert "## Recent Failures" not in body


def test_rendered_workflow_bucket_shows_overflow_note_when_capped() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[
                    build_item(item_id=f"sonar:{index:02d}", status="open").model_copy(
                        update={"source_reference": f"issue-{index}"}
                    )
                    for index in range(12)
                ],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="change_requests_opened", title="Change Requests Opened", items=[]
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "| 12 | 0 | 0 | 0 | 0 |" in body
    assert "_2 more items not shown._" in body
    assert "`sonar:09`" in body
    assert "`sonar:10`" not in body
    assert "`sonar:11`" not in body
    assert "zeroone-workflow-hidden-items" in body


def test_workflow_queue_orders_items_by_area_and_file() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[
                    build_item(item_id="sonar:z", status="open").model_copy(
                        update={"file": "src/beta/zeta.py", "source_reference": "issue-z"}
                    ),
                    build_item(item_id="sonar:a", status="open").model_copy(
                        update={"file": "apps/api/alpha.py", "source_reference": "issue-a"}
                    ),
                    build_item(item_id="sonar:b", status="open").model_copy(
                        update={"file": "apps/api/beta.py", "source_reference": "issue-b"}
                    ),
                ],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="change_requests_opened", title="Change Requests Opened", items=[]
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    alpha_index = body.index("`sonar:a`")
    beta_index = body.index("`sonar:b`")
    zeta_index = body.index("`sonar:z`")
    assert alpha_index < beta_index < zeta_index
    assert "`apps/api`" in body
    assert "`src/beta`" in body


def test_parse_accepts_legacy_workflow_summary_without_area_column() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Work Queue

## Open Candidates

### Overview

| Open | In progress | Change requests opened | Failed | Done |
|---|---|---|---|---|
| 1 | 0 | 0 | 0 | 0 |

### Queue Auto-fix

| Item | File | Priority | Next Step | Summary |
|---|---|---|---|---|
| `sonar:1` | `service.py` | Low | Queue Auto-fix | Simplify boolean comparison |

### Needs Review

No items.

### In Flight

No items.

### Completed

No items.

### Work Type Breakdown

| Work Type | Count |
|---|---|
| Simplify boolean comparison | 1 |

<details>
<summary><code>sonar:1</code> details</summary>

```json
{
  "id": "sonar:1",
  "source": "sonarqube",
  "type": "code_smell_fix",
  "status": "open",
  "title": "Simplify boolean comparison",
  "summary": "Replace explicit boolean equality with direct truthiness.",
  "priority": "low",
  "source_reference": "issue-1",
  "file": "src/service.py",
  "line": 42,
  "rule": "python:S1125",
  "severity": "LOW"
}
```

</details>

## Change Request Reviews

No items.

## Rejected Or Ignored

No items.

## Recent Failures

No items.
"""

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert [item.id for item in document.sections[0].items] == ["sonar:1"]


def test_parse_round_trips_hidden_workflow_items_from_machine_block() -> None:
    renderer = DashboardRenderer()
    parser = DashboardParser()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[
                    build_item(item_id=f"sonar:{index:02d}", status="open").model_copy(
                        update={"source_reference": f"issue-{index}"}
                    )
                    for index in range(12)
                ],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="change_requests_opened", title="Change Requests Opened", items=[]
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    ids = {item.id for item in document.sections[0].items}
    assert len(ids) == 12
    assert {"sonar:10", "sonar:11"} <= ids


def test_render_prefers_policy_eligible_queue_items_under_bucket_cap() -> None:
    renderer = DashboardRenderer()
    blocked_items = [
        build_item(item_id=f"sonar:block-{index}").model_copy(
            update={
                "file": f"src/a_block_{index}.py",
                "source_reference": f"issue-block-{index}",
                "automation_severity": "high",
                "severity": "HIGH",
            }
        )
        for index in range(10)
    ]
    eligible_item = build_item(item_id="sonar:eligible").model_copy(
        update={
            "file": "src/z_eligible.py",
            "source_reference": "issue-eligible",
            "automation_severity": "low",
            "severity": "LOW",
        }
    )

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[*blocked_items, eligible_item],
            ),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="change_requests_opened", title="Change Requests Opened", items=[]
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
        policy_state=DashboardPolicyState(
            severity_policy=[
                DashboardSeverityPolicyStateEntry(severity="low", enabled=True),
                DashboardSeverityPolicyStateEntry(severity="medium", enabled=False),
                DashboardSeverityPolicyStateEntry(severity="high", enabled=False),
            ]
        ),
    )

    assert "| `sonar:eligible` | `src` | `z_eligible.py` |" in body
    assert "_1 more items not shown._" in body


def test_rendered_dashboard_body_surfaces_linked_review_state_in_summary_table() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(key="open_candidates", title="Open Candidates", items=[]),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="change_requests_opened",
                title="Change Requests Opened",
                items=[
                    build_item(item_id="sonar:reviewed", status="change_request_opened").model_copy(
                        update={
                            "merge_request_iid": 17,
                            "merge_request_url": (
                                "https://gitlab.example.com/group/project/-/merge_requests/17"
                            ),
                            "review_status": "findings_present",
                            "review_findings_count": 2,
                            "reviewed_head_sha": "abc123def456",
                            "retry_eligible": True,
                            "review_feedback_summary": ("Ordering changed in a shared code path."),
                        }
                    )
                ],
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "⚠️ Findings present" in body


def test_completed_workflow_items_render_review_outcome_not_raw_review_note() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="completed",
                title="Completed",
                items=[
                    build_item(item_id="sonar:done", status="done").model_copy(
                        update={
                            "review_status": "no_findings",
                            "review_findings_count": 0,
                            "reviewed_head_sha": "abc123def456",
                            "review_feedback_summary": "Looks safe.",
                        }
                    )
                ],
            ),
            DashboardSection(key="open_candidates", title="Open Candidates", items=[]),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            empty_change_requests_opened_section(),
            empty_change_request_reviews_section(),
            DashboardSection(
                key="rejected_or_ignored",
                title="Rejected Or Ignored",
                items=[],
            ),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "### Completed" in body
    assert "✅ No findings" in body
    assert "review: no_findings" not in body


def test_parse_round_trips_dashboard_item_review_metadata() -> None:
    renderer = DashboardRenderer()
    parser = DashboardParser()
    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="change_requests_opened",
                title="Change Requests Opened",
                items=[
                    build_item(item_id="sonar:1", status="change_request_opened").model_copy(
                        update={
                            "merge_request_iid": 17,
                            "merge_request_url": (
                                "https://gitlab.example.com/group/project/-/merge_requests/17"
                            ),
                            "review_status": "findings_present",
                            "review_findings_count": 1,
                            "reviewed_head_sha": "abc123",
                            "review_feedback_summary": "Concrete ordering regression found.",
                            "review_feedback_updated_at": datetime(2026, 4, 12, 10, 0, tzinfo=UTC),
                            "review_confidence": 0.82,
                            "review_confidence_reason": (
                                "The changed diff directly alters output ordering."
                            ),
                        }
                    )
                ],
            ),
            DashboardSection(key="open_candidates", title="Open Candidates", items=[]),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(key="completed", title="Completed", items=[]),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    item = document.items_by_id()["sonar:1"]
    assert item.review_status == "findings_present"
    assert item.review_findings_count == 1
    assert item.reviewed_head_sha == "abc123"
    assert item.review_feedback_summary == "Concrete ordering regression found."
    assert item.review_feedback_updated_at == datetime(2026, 4, 12, 10, 0, tzinfo=UTC)
    assert item.review_confidence == 0.82
    assert item.review_confidence_reason == "The changed diff directly alters output ordering."


def test_parse_rejects_free_form_content_in_managed_section() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Work Queue

## Open Candidates

unexpected free-form text

## In Progress

No items.

## Change Requests Opened

No items.

## Completed

No items.

## Change Request Reviews

No items.

## Rejected Or Ignored

No items.

## Recent Failures

No items.
"""

    try:
        parser.parse(
            issue_id=10,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Work Queue",
            body=body,
        )
    except DashboardParseError as error:
        assert "parseable item blocks" in str(error)
    else:
        raise AssertionError("Expected DashboardParseError for unsupported free-form content.")


def test_parse_accepts_summary_table_followed_by_multiple_item_blocks() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Work Queue

## Open Candidates

### Overview

| Open | In progress | Change requests opened | Failed | Done |
|---|---|---|---|---|
| 2 | 0 | 0 | 0 | 0 |

### Queue Auto-fix

| Item | Area | File | Priority | Next Step | Summary |
|---|---|---|---|---|---|
| `sonar:1` | `src` | `service.py` | Low | Queue Auto-fix | Simplify boolean comparison |
| `sonar:2` | `src` | `other.py` | Medium | Queue Auto-fix | Remove unused variable |

### Needs Review

No items.

### In Flight

No items.

### Completed

No items.

### Dismissed

No items.

### Work Type Breakdown

| Work Type | Count |
|---|---|
| Remove unused variable | 1 |
| Simplify boolean comparison | 1 |

<details>
<summary><code>sonar:1</code> details</summary>

```json
{
  "id": "sonar:1",
  "source": "sonarqube",
  "type": "code_smell_fix",
  "status": "open",
  "title": "Simplify boolean comparison",
  "summary": "Replace explicit boolean equality with direct truthiness.",
  "priority": "low",
  "source_reference": "issue-1",
  "file": "src/service.py",
  "line": 42,
  "rule": "python:S1125",
  "severity": "LOW"
}
```

</details>

<details>
<summary><code>sonar:2</code> details</summary>

```json
{
  "id": "sonar:2",
  "source": "sonarqube",
  "type": "code_smell_fix",
  "status": "open",
  "title": "Remove unused variable",
  "summary": "Delete the unused local variable.",
  "priority": "medium",
  "source_reference": "issue-2",
  "file": "src/other.py",
  "line": 9,
  "rule": "python:S1481",
  "severity": "MEDIUM"
}
```

</details>

## Change Request Reviews

No items.

## Rejected Or Ignored

No items.

## Recent Failures

No items.
"""

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert [item.id for item in document.sections[0].items] == ["sonar:1", "sonar:2"]


def test_parse_rejects_item_heading_id_mismatch() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Work Queue

## Open Candidates

<details>
<summary><code>sonar:1</code> details</summary>

```json
{
  "id": "sonar:2",
  "source": "sonarqube",
  "type": "code_smell_fix",
  "status": "open",
  "title": "Simplify boolean comparison",
  "summary": "Replace explicit boolean equality with direct truthiness.",
  "priority": "low",
  "source_reference": "issue-1"
}
```

</details>

## In Progress

No items.

## Change Requests Opened

No items.

## Completed

No items.

## Change Request Reviews

No items.

## Rejected Or Ignored

No items.

## Recent Failures

No items.
"""

    try:
        parser.parse(
            issue_id=10,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Work Queue",
            body=body,
        )
    except DashboardParseError as error:
        assert "heading ID did not match" in str(error)
    else:
        raise AssertionError("Expected DashboardParseError for mismatched item IDs.")


def test_parse_rejects_unsupported_summary_table_shape() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Work Queue

## Open Candidates

| ID | Source | Type | File | Rule | Status |
|---|---|---|---|---|---|
| `sonar:1` | sonarqube | code_smell_fix | `src/service.py` | `python:S1125` | `open` |

<details>
<summary><code>sonar:1</code> details</summary>

```json
{
  "id": "sonar:1",
  "source": "sonarqube",
  "type": "code_smell_fix",
  "status": "open",
  "title": "Simplify boolean comparison",
  "summary": "Replace explicit boolean equality with direct truthiness.",
  "priority": "low",
  "source_reference": "issue-1"
}
```

</details>

## In Progress

No items.

## Change Requests Opened

No items.

## Completed

No items.

## Change Request Reviews

No items.

## Rejected Or Ignored

No items.

## Recent Failures

No items.
"""

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert document.items_by_id()["sonar:1"].id == "sonar:1"


def test_parse_accepts_unknown_projection_layout_when_item_blocks_are_valid() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Work Queue

## Open Candidates

### Future Queue

| Item | Bucket | Confidence | Summary |
|---|---|---|---|
| `sonar:1` | Ready | 0.90 | Simplify boolean comparison |

<details>
<summary><code>sonar:1</code> details</summary>

```json
{
  "id": "sonar:1",
  "source": "sonarqube",
  "type": "code_smell_fix",
  "status": "open",
  "title": "Simplify boolean comparison",
  "summary": "Replace explicit boolean equality with direct truthiness.",
  "priority": "low",
  "source_reference": "issue-1"
}
```

</details>

## In Progress

No items.

## Change Requests Opened

No items.

## Completed

No items.

## Change Request Reviews

No items.

## Rejected Or Ignored

No items.

## Recent Failures

No items.
"""

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert document.items_by_id()["sonar:1"].status == "open"


def test_parse_accepts_unknown_projection_layout_without_item_blocks() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Work Queue

## Open Candidates

### Future Queue

| Item | Bucket | Confidence | Summary |
|---|---|---|---|
| `sonar:1` | Ready | 0.90 | Simplify boolean comparison |

## In Progress

No items.

## Change Requests Opened

No items.

## Completed

No items.

## Change Request Reviews

### Future Review Projection

| MR | Queue | Summary |
|---|---|---|
| [!77](https://gitlab.example.com/group/project/-/merge_requests/77) | Review | Follow-up summary |

## Rejected Or Ignored

No items.

## Recent Failures

No items.
"""

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert document.sections[0].items == []
    assert document.items_by_id() == {}


def test_parse_accepts_legacy_dashboard_fixture() -> None:
    parser = DashboardParser()
    body = (FIXTURES_DIR / "legacy_workflow_with_dismissed.md").read_text()

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert document.schema_version == 0
    assert document.items_by_id() == {}


def test_parse_accepts_legacy_pre_dismissed_workflow_fixture_with_items() -> None:
    parser = DashboardParser()
    body = (FIXTURES_DIR / "legacy_workflow_pre_dismissed_with_items.md").read_text()

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    items = document.items_by_id()
    assert items["sonar:1"].status == "open"
    assert items["sonar:2"].status == "in_progress"


def test_parse_accepts_legacy_pre_area_workflow_fixture_with_items() -> None:
    parser = DashboardParser()
    body = (FIXTURES_DIR / "legacy_workflow_pre_area_with_items.md").read_text()

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    items = document.items_by_id()
    assert items["sonar:3"].status == "open"
    assert items["sonar:4"].status == "failed"


def test_parse_accepts_legacy_review_history_fixture_with_items() -> None:
    parser = DashboardParser()
    body = (FIXTURES_DIR / "legacy_review_history_with_items.md").read_text()

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    items = document.items_by_id()
    assert items["mr-review:77:abc123def456"].review_status == "findings_present"
    assert items["mr-review:77:abc123def456"].review_findings_count == 2


def test_render_uses_placeholders_for_missing_file_and_rule_fields() -> None:
    renderer = DashboardRenderer()
    item = DashboardItem(
        id="mr-review:42:abc123",
        source="pull_request_review",
        type="review_status",
        status="done",
        title="Review complete",
        summary="No findings.",
        priority="low",
        source_reference="mr-42",
        merge_request_iid=42,
        review_status="no_findings",
        reviewed_head_sha="abc123",
    )

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="change_request_reviews",
                title="Change Request Reviews",
                items=[item],
            )
        ],
    )

    assert "### Needs Attention" in body
    assert "### Review History" in body
    assert "No items." in body
    assert "| !42 | 1 | ✅ No findings | 0 | - | 🟢 Low | No findings. | `abc123` |" in body
    assert '"review_status": "no_findings"' in body
    assert '"file":' not in body
    assert '"rule":' not in body


def test_parse_round_trips_workflow_items_from_combined_workflow_section() -> None:
    renderer = DashboardRenderer()
    parser = DashboardParser()
    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(
                key="open_candidates",
                title="Open Candidates",
                items=[build_item(item_id="sonar:open", status="open")],
            ),
            DashboardSection(
                key="in_progress",
                title="In Progress",
                items=[build_item(item_id="sonar:progress", status="in_progress")],
            ),
            DashboardSection(
                key="change_requests_opened",
                title="Change Requests Opened",
                items=[build_item(item_id="sonar:mr", status="change_request_opened")],
            ),
            DashboardSection(
                key="completed",
                title="Completed",
                items=[build_item(item_id="sonar:done", status="done")],
            ),
            empty_change_request_reviews_section(),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert [item.id for item in document.sections[0].items] == ["sonar:open"]
    assert [item.id for item in document.sections[1].items] == ["sonar:progress"]
    assert [item.id for item in document.sections[2].items] == ["sonar:mr"]
    assert [item.id for item in document.sections[3].items] == ["sonar:done"]


def test_rendered_dashboard_body_includes_schema_marker_and_policy_sections() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[DashboardSection(key="open_candidates", title="Open Candidates", items=[])],
    )

    assert "<!-- zeroone-ops:dashboard-schema:v2 -->" in body
    assert "zeroone-dashboard-manifest" in body
    assert "## Automation Severity Policy" in body
    assert "## Excluded Issue Classes" in body
    assert "## Issue Class Inventory" in body
    assert "## Operator Policy Actions" in body
    assert "/zeroone policy severity enable high" in body
    assert "zeroone-policy-state" in body


def test_parse_ignores_direct_policy_markdown_edits_as_non_authoritative() -> None:
    parser = DashboardParser()
    body = """<!-- zeroone-ops:dashboard-schema:v1 -->

Machine-managed remediation and review items for this repository.

## Automation Severity Policy

| Severity | Automation Status | Reason |
|---|---|---|
| `low` | blocked by severity policy | manually edited checkbox |
| `medium` | eligible for automation | - |
| `high` | eligible for automation | manually edited checkbox |

## Excluded Issue Classes

No items.

## Issue Class Inventory

No items.

## Operator Policy Actions

Use strict dashboard issue comments with the exact `/zeroone policy` prefix.

| Action | Command |
|---|---|

Direct markdown edits and raw checkbox changes in this dashboard are display-only
and do not mutate operator policy.

## Open Candidates

### Overview

| Open | In progress | Change requests opened | Failed | Done |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |

### Queue Auto-fix

No items.

### Needs Review

No items.

### In Flight

No items.

### Completed

No items.

### Dismissed

No items.

### Work Type Breakdown

No items.
"""

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert document.schema_version == 1
    assert document.policy_view.severity_policy == []
    assert document.sections[0].items == []


def test_parse_prefers_canonical_policy_state_block_over_visible_checkbox_edits() -> None:
    parser = DashboardParser()
    body = """<!-- zeroone-ops:dashboard-schema:v1 -->

Machine-managed remediation and review items for this repository.

## Automation Severity Policy

| Severity | Automation Status | Reason |
|---|---|---|
| `low` | blocked by severity policy | manually edited checkbox |
| `medium` | eligible for automation | - |
| `high` | eligible for automation | manually edited checkbox |

## Excluded Issue Classes

No items.

## Issue Class Inventory

No items.

## Operator Policy Actions

<details>
<summary><code>zeroone-policy-state</code> machine state</summary>

```json
{
  "severity_policy": [
    {
      "enabled": true,
      "severity": "low"
    },
    {
      "enabled": false,
      "severity": "medium"
    },
    {
      "enabled": false,
      "severity": "high"
    }
  ]
}
```

</details>

Use strict dashboard issue comments with the exact `/zeroone policy` prefix.

| Action | Command |
|---|---|

Direct markdown edits and raw checkbox changes in this dashboard are display-only
and do not mutate operator policy.

## Open Candidates

### Overview

| Open | In progress | Change requests opened | Failed | Done |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |

### Queue Auto-fix

No items.

### Needs Review

No items.

### In Flight

No items.

### Completed

No items.

### Dismissed

No items.

### Work Type Breakdown

No items.
"""

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert [entry.severity for entry in document.policy_state.severity_policy] == [
        "low",
        "medium",
        "high",
    ]
    assert [entry.enabled for entry in document.policy_state.severity_policy] == [
        True,
        False,
        False,
    ]


def test_parse_treats_missing_schema_marker_as_legacy_v0() -> None:
    renderer = DashboardRenderer()
    parser = DashboardParser()
    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[DashboardSection(key="open_candidates", title="Open Candidates", items=[])],
        schema_version=1,
    )
    legacy_body = "\n".join(body.splitlines()[2:]) + "\n"

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=legacy_body,
    )

    assert document.schema_version == 0


def test_parse_accepts_current_schema_dashboard_without_manifest_for_transition() -> None:
    parser = DashboardParser()
    body = """<!-- zeroone-ops:dashboard-schema:v2 -->

Machine-managed remediation and review items for this repository.

## Automation Severity Policy

| Severity | Automation Status | Reason |
|---|---|---|
| `low` | eligible for automation | - |
| `medium` | eligible for automation | - |
| `high` | blocked by severity policy | configured default |

## Excluded Issue Classes

No items.

## Issue Class Inventory

No items.

## Operator Policy Actions

Use strict dashboard issue comments with the exact `/zeroone policy` prefix.

| Action | Command |
|---|---|

Direct markdown edits and raw checkbox changes in this dashboard are display-only
and do not mutate operator policy.

## Open Candidates

### Overview

| Open | In progress | Change requests opened | Failed | Done |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |

### Queue Auto-fix

No items.

### Needs Review

No items.

### In Flight

No items.

### Completed

No items.

### Dismissed

No items.

### Work Type Breakdown

No items.
"""

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        body=body,
    )

    assert document.schema_version == 2
    assert document.sections[0].items == []


def test_parse_rejects_manifest_mismatch() -> None:
    parser = DashboardParser()
    body = """<!-- zeroone-ops:dashboard-schema:v2 -->

Machine-managed remediation and review items for this repository.

<details>
<summary><code>zeroone-dashboard-manifest</code> machine state</summary>

```json
{
  "section_item_counts": {
    "completed": 0,
    "in_progress": 0,
    "change_request_reviews": 0,
    "change_requests_opened": 0,
    "open_candidates": 99,
    "recent_failures": 0,
    "rejected_or_ignored": 0
  },
  "total_item_count": 99,
  "workflow_item_count": 99
}
```

</details>

## Automation Severity Policy

| Severity | Automation Status | Reason |
|---|---|---|
| `low` | eligible for automation | - |
| `medium` | eligible for automation | - |
| `high` | blocked by severity policy | configured default |

## Excluded Issue Classes

No items.

## Issue Class Inventory

No items.

## Operator Policy Actions

Use strict dashboard issue comments with the exact `/zeroone policy` prefix.

| Action | Command |
|---|---|

Direct markdown edits and raw checkbox changes in this dashboard are display-only
and do not mutate operator policy.

## Open Candidates

### Overview

| Open | In progress | Change requests opened | Failed | Done |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |

### Queue Auto-fix

No items.

### Needs Review

No items.

### In Flight

No items.

### Completed

No items.

### Dismissed

No items.

### Work Type Breakdown

No items.
"""

    try:
        parser.parse(
            issue_id=10,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Work Queue",
            body=body,
        )
    except DashboardParseError as error:
        assert "manifest did not match" in str(error)
    else:
        raise AssertionError("Expected DashboardParseError for manifest mismatch.")


def test_parse_rejects_manifest_era_dashboard_without_schema_marker() -> None:
    parser = DashboardParser()
    body = """Machine-managed remediation and review items for this repository.

<details>
<summary><code>zeroone-dashboard-manifest</code> machine state</summary>

```json
{
  "section_item_counts": {
    "completed": 0,
    "in_progress": 0,
    "change_request_reviews": 0,
    "change_requests_opened": 0,
    "open_candidates": 0,
    "recent_failures": 0,
    "rejected_or_ignored": 0
  },
  "total_item_count": 0,
  "workflow_item_count": 0
}
```

</details>

## Automation Severity Policy

| Severity | Automation Status | Reason |
|---|---|---|
| `low` | eligible for automation | - |
| `medium` | eligible for automation | - |
| `high` | blocked by severity policy | configured default |

## Excluded Issue Classes

No items.

## Issue Class Inventory

No items.

## Operator Policy Actions

Use strict dashboard issue comments with the exact `/zeroone policy` prefix.

| Action | Command |
|---|---|

Direct markdown edits and raw checkbox changes in this dashboard are display-only
and do not mutate operator policy.

## Open Candidates

### Overview

| Open | In progress | Change requests opened | Failed | Done |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |

### Queue Auto-fix

No items.

### Needs Review

No items.

### In Flight

No items.

### Completed

No items.

### Dismissed

No items.

### Work Type Breakdown

No items.
"""

    try:
        parser.parse(
            issue_id=10,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Work Queue",
            body=body,
        )
    except DashboardParseError as error:
        assert "schema marker was missing" in str(error)
    else:
        raise AssertionError("Expected DashboardParseError for missing schema marker.")


def test_render_older_schema_version_does_not_emit_manifest_block() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[DashboardSection(key="open_candidates", title="Open Candidates", items=[])],
        schema_version=1,
    )

    assert "<!-- zeroone-ops:dashboard-schema:v1 -->" in body
    assert "zeroone-dashboard-manifest" not in body
