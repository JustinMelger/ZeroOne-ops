from datetime import UTC, datetime

from ai_sonar_bot.models.dashboard import DashboardItem, DashboardSection
from ai_sonar_bot.services.dashboard_parser import DashboardParseError, DashboardParser
from ai_sonar_bot.services.dashboard_renderer import DashboardRenderer


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
        validation_commands=["uv run pytest"],
    )


def test_parse_round_trips_rendered_dashboard_body() -> None:
    renderer = DashboardRenderer()
    parser = DashboardParser()
    body = renderer.render(
        title="AI Code Ops Dashboard",
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
        title="AI Code Ops Dashboard",
        body=body,
    )

    assert document.sections[0].items[0].id == "sonar:1"
    assert document.sections[0].items[0].rule == "python:S1125"


def test_parse_round_trips_dashboard_item_datetime_metadata() -> None:
    renderer = DashboardRenderer()
    parser = DashboardParser()
    body = renderer.render(
        title="AI Code Ops Dashboard",
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
        title="AI Code Ops Dashboard",
        body=body,
    )

    item = document.items_by_id()["sonar:1"]
    assert item.last_run_id == "run-1"
    assert item.status_updated_at == datetime(2026, 4, 7, 12, 0, tzinfo=UTC)


def test_rendered_dashboard_body_includes_human_readable_summary_table() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Dashboard",
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
    assert "| Item | Status | Priority | Summary |" in body
    assert "`sonar:1` (src/service.py)" in body
    assert "Open" in body
    assert "Low" in body
    assert "<details>" in body
    assert "<summary><code>sonar:1</code> details</summary>" in body


def test_rendered_dashboard_body_keeps_new_workflow_layout_when_empty() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Dashboard",
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
    assert "### All Workflow Items" in body
    assert "## In Progress" not in body
    assert "## Merge Requests Opened" not in body
    assert "## Completed" not in body


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
        title="AI Code Ops Dashboard",
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
    assert "| MR | Outcome | Findings | Priority | Summary |" in body
    assert "[!363](https://gitlab.example.com/group/project/-/merge_requests/363)" in body
    assert "⚠️ Findings present" in body
    assert "License logic change with visible redirect impact." in body
    assert "### All Reviews" in body
    assert "| MR | Outcome | Findings | Priority | Summary | Reviewed SHA |" in body
    assert "`abc123de`" in body


def test_rendered_dashboard_body_surfaces_failure_note_in_summary_table() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Dashboard",
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

    assert "| Item | Status | Priority | Summary |" in body
    assert "Merge request metadata is inaccessible from GitLab." in body


def test_rendered_workflow_section_uses_specialized_workflow_summary_layout() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Dashboard",
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
    assert "### All Workflow Items" in body
    assert "`sonar:open` (src/service.py)" in body
    assert "`sonar:progress` (src/service.py)" in body
    assert "[!42](https://gitlab.example.com/group/project/-/merge_requests/42)" in body


def test_render_hides_legacy_empty_workflow_sections_when_combined_view_is_present() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Dashboard",
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
    assert "## Completed" not in body
    assert "## Rejected Or Ignored" not in body
    assert "## Recent Failures" not in body


def test_rendered_dashboard_body_surfaces_linked_review_state_in_summary_table() -> None:
    renderer = DashboardRenderer()

    body = renderer.render(
        title="AI Code Ops Dashboard",
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

    assert "review: findings_present" in body
    assert "findings: 2" in body
    assert "sha: abc123de" in body
    assert "retry: eligible" in body
    assert "Ordering changed in a shared code path." in body


def test_parse_round_trips_dashboard_item_review_metadata() -> None:
    renderer = DashboardRenderer()
    parser = DashboardParser()
    body = renderer.render(
        title="AI Code Ops Dashboard",
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
        title="AI Code Ops Dashboard",
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
    body = """# AI Code Ops Dashboard

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
            title="AI Code Ops Dashboard",
            body=body,
        )
    except DashboardParseError as error:
        assert "parseable item blocks" in str(error)
    else:
        raise AssertionError("Expected DashboardParseError for unsupported free-form content.")


def test_parse_accepts_summary_table_followed_by_multiple_item_blocks() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Dashboard

## Open Candidates

### Overview

| Open | In progress | MR opened | Failed | Done |
|---|---|---|---|---|
| 2 | 0 | 0 | 0 | 0 |

### Needs Attention

| Item | Status | Priority | Summary |
|---|---|---|---|
| `sonar:1` (src/service.py) | Open | Low | Simplify boolean equality check. |
| `sonar:2` (src/other.py) | Open | Medium | Delete the unused local variable. |

### All Workflow Items

| Item | Status | Priority | Summary |
|---|---|---|---|
| `sonar:1` (src/service.py) | Open | Low | Simplify boolean equality check. |
| `sonar:2` (src/other.py) | Open | Medium | Delete the unused local variable. |

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

    document = parser.parse(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Dashboard",
        body=body,
    )

    assert [item.id for item in document.sections[0].items] == ["sonar:1", "sonar:2"]


def test_parse_rejects_item_heading_id_mismatch() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Dashboard

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
            title="AI Code Ops Dashboard",
            body=body,
        )
    except DashboardParseError as error:
        assert "heading ID did not match" in str(error)
    else:
        raise AssertionError("Expected DashboardParseError for mismatched item IDs.")


def test_parse_rejects_unsupported_summary_table_shape() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Dashboard

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
            title="AI Code Ops Dashboard",
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
        title="AI Code Ops Dashboard",
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
    assert "| !42 | ✅ No findings | 0 | 🟢 Low | No findings. | `abc123` |" in body
    assert '"review_status": "no_findings"' in body
    assert '"file":' not in body
    assert '"rule":' not in body


def test_parse_round_trips_workflow_items_from_combined_workflow_section() -> None:
    renderer = DashboardRenderer()
    parser = DashboardParser()
    body = renderer.render(
        title="AI Code Ops Dashboard",
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
        title="AI Code Ops Dashboard",
        body=body,
    )

    assert [item.id for item in document.sections[0].items] == ["sonar:open"]
    assert [item.id for item in document.sections[1].items] == ["sonar:progress"]
    assert [item.id for item in document.sections[2].items] == ["sonar:mr"]
    assert [item.id for item in document.sections[3].items] == ["sonar:done"]
