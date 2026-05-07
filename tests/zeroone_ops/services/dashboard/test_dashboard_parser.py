from datetime import UTC, datetime

from zeroone_ops.models.dashboard import DashboardItem, DashboardSection
from zeroone_ops.services.dashboard.dashboard_parser import (
    DashboardParseError,
    DashboardParser,
)
from zeroone_ops.services.dashboard.dashboard_renderer import DashboardRenderer


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
            DashboardSection(
                key="merge_requests_opened",
                title="Merge Requests Opened",
                items=[],
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
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
            DashboardSection(
                key="merge_requests_opened",
                title="Merge Requests Opened",
                items=[],
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
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
            DashboardSection(
                key="merge_requests_opened",
                title="Merge Requests Opened",
                items=[],
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
            DashboardSection(
                key="rejected_or_ignored",
                title="Rejected Or Ignored",
                items=[],
            ),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "### Overview" in body
    assert "| Open | In progress | MR opened | Failed | Done |" in body
    assert "| 1 | 0 | 0 | 0 | 0 |" in body
    assert "### Needs Attention" in body
    assert "| Item | File | Priority | Next Step | Summary |" in body
    assert "`sonar:1`" in body
    assert "`service.py`" in body
    assert "Queue Auto-fix" in body
    assert "Simplify boolean comparison" in body
    assert "### In Flight" in body
    assert "### Completed" in body
    assert "### Work Type Breakdown" in body
    assert "<details>" in body
    assert "<summary><code>sonar:1</code> details</summary>" in body


def test_rendered_dashboard_body_keeps_new_workflow_layout_when_empty() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(key="open_candidates", title="Open Candidates", items=[]),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="merge_requests_opened",
                title="Merge Requests Opened",
                items=[],
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
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
    assert "| Open | In progress | MR opened | Failed | Done |" in body
    assert "| 0 | 0 | 0 | 0 | 0 |" in body
    assert "### Needs Attention" in body
    assert "### In Flight" in body
    assert "### Completed" in body
    assert "### Work Type Breakdown" in body
    assert "## In Progress" not in body
    assert "## Merge Requests Opened" not in body
    assert "\n## Completed\n" not in body


def test_rendered_dashboard_body_keeps_manual_review_rejection_visible_in_needs_attention() -> None:
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
            DashboardSection(
                key="merge_requests_opened",
                title="Merge Requests Opened",
                items=[],
            ),
            DashboardSection(key="completed", title="Completed", items=[]),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
            DashboardSection(
                key="rejected_or_ignored",
                title="Rejected Or Ignored",
                items=[],
            ),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "`sonar:manual`" in body
    assert "Review Manually" in body
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
                key="merge_request_reviews",
                title="Merge Request Reviews",
                items=[review_item],
            )
        ],
    )

    assert "### Overview" in body
    assert "| Reviews | Needs attention | Findings total | High priority |" in body
    assert "| 1 | 1 | 3 | 1 |" in body
    assert "### Needs Attention" in body
    assert "| MR | Outcome | Findings | Confidence | Priority | Summary |" in body
    assert "[!363](https://gitlab.example.com/group/project/-/merge_requests/363)" in body
    assert "⚠️ Findings present" in body
    assert (
        "| [!363](https://gitlab.example.com/group/project/-/merge_requests/363) | "
        "⚠️ Findings present | 3 | - | 🔴 High | "
        "License logic change with visible redirect impact. | `abc123de` |" in body
    )
    assert "License logic change with visible redirect impact." in body
    assert "### All Reviews" in body
    assert "| MR | Outcome | Findings | Confidence | Priority | Summary | Reviewed SHA |" in body
    assert "`abc123de`" in body


def test_rendered_dashboard_body_surfaces_failure_note_in_summary_table() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(key="open_candidates", title="Open Candidates", items=[]),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(key="merge_requests_opened", title="Merge Requests Opened", items=[]),
            DashboardSection(key="completed", title="Completed", items=[]),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
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

    assert "| Item | File | Priority | Next Step | Summary |" in body
    assert "Investigate Failure" in body
    assert "Simplify boolean comparison" in body


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
            DashboardSection(key="merge_requests_opened", title="Merge Requests Opened", items=[]),
            DashboardSection(key="completed", title="Completed", items=[]),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "Retry Auto-fix" in body
    assert "Retry eligible. GitLab token was expired during publish." in body


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
            DashboardSection(key="merge_requests_opened", title="Merge Requests Opened", items=[]),
            DashboardSection(key="completed", title="Completed", items=[]),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "Review Retry Blocker" in body
    assert "Retry blocked: Latest review outcome requires manual review." in body


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
                key="merge_requests_opened",
                title="Merge Requests Opened",
                items=[
                    build_item(item_id="sonar:mr", status="mr_opened").model_copy(
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
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "### Overview" in body
    assert "| Open | In progress | MR opened | Failed | Done |" in body
    assert "| 1 | 1 | 1 | 0 | 0 |" in body
    assert "### Needs Attention" in body
    assert "| Item | File | Priority | Next Step | Summary |" in body
    assert "### In Flight" in body
    assert "| Item | Status | Priority | Review Summary |" in body
    assert "### Completed" in body
    assert "### Work Type Breakdown" in body
    assert "`sonar:open`" in body
    assert "`sonar:progress`" in body
    assert "`sonar:mr`" in body
    assert "Queue Auto-fix" in body
    assert "📦 Mr Opened" in body


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
            DashboardSection(key="merge_requests_opened", title="Merge Requests Opened", items=[]),
            DashboardSection(key="completed", title="Completed", items=[]),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
            DashboardSection(key="rejected_or_ignored", title="Rejected Or Ignored", items=[]),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "## Open Candidates" in body
    assert "## In Progress" not in body
    assert "## Merge Requests Opened" not in body
    assert "\n## Completed\n" not in body
    assert "## Rejected Or Ignored" not in body
    assert "## Recent Failures" not in body


def test_rendered_dashboard_body_surfaces_linked_review_state_in_summary_table() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Work Queue",
        sections=[
            DashboardSection(key="open_candidates", title="Open Candidates", items=[]),
            DashboardSection(key="in_progress", title="In Progress", items=[]),
            DashboardSection(
                key="merge_requests_opened",
                title="Merge Requests Opened",
                items=[
                    build_item(item_id="sonar:reviewed", status="mr_opened").model_copy(
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
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
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
            DashboardSection(
                key="merge_requests_opened",
                title="Merge Requests Opened",
                items=[],
            ),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
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
                key="merge_requests_opened",
                title="Merge Requests Opened",
                items=[
                    build_item(item_id="sonar:1", status="mr_opened").model_copy(
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
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
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

## Merge Requests Opened

No items.

## Completed

No items.

## Merge Request Reviews

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

| Open | In progress | MR opened | Failed | Done |
|---|---|---|---|---|
| 2 | 0 | 0 | 0 | 0 |

### Needs Attention

| Item | File | Priority | Next Step | Summary |
|---|---|---|---|---|
| `sonar:1` | `service.py` | Low | Queue Auto-fix | Simplify boolean comparison |
| `sonar:2` | `other.py` | Medium | Queue Auto-fix | Remove unused variable |

### In Flight

No items.

### Completed

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

## Merge Request Reviews

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

## Merge Requests Opened

No items.

## Completed

No items.

## Merge Request Reviews

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

## Merge Requests Opened

No items.

## Completed

No items.

## Merge Request Reviews

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
        assert "unsupported free-form content" in str(error)
    else:
        raise AssertionError("Expected DashboardParseError for malformed summary table.")


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
                key="merge_request_reviews",
                title="Merge Request Reviews",
                items=[item],
            )
        ],
    )

    assert "### Needs Attention" in body
    assert "No items." in body
    assert "| !42 | ✅ No findings | 0 | - | 🟢 Low | No findings. | `abc123` |" in body
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
                key="merge_requests_opened",
                title="Merge Requests Opened",
                items=[build_item(item_id="sonar:mr", status="mr_opened")],
            ),
            DashboardSection(
                key="completed",
                title="Completed",
                items=[build_item(item_id="sonar:done", status="done")],
            ),
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
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

    assert "<!-- zeroone-ops:dashboard-schema:v1 -->" in body
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

| Open | In progress | MR opened | Failed | Done |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |

### Needs Attention

No items.

### In Flight

No items.

### Completed

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

| Open | In progress | MR opened | Failed | Done |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 |

### Needs Attention

No items.

### In Flight

No items.

### Completed

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
