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
            DashboardSection(key="merge_request_reviews", title="Merge Request Reviews", items=[]),
            DashboardSection(
                key="rejected_or_ignored",
                title="Rejected Or Ignored",
                items=[],
            ),
            DashboardSection(key="recent_failures", title="Recent Failures", items=[]),
        ],
    )

    assert "| ID | Source | Type | File | Rule | Status | Priority |" in body
    expected_row = (
        "| `sonar:1` | sonarqube | code_smell_fix | "
        "`src/service.py` | `python:S1125` | `open` | `low` |"
    )
    assert expected_row in body


def test_parse_rejects_free_form_content_in_managed_section() -> None:
    parser = DashboardParser()
    body = """# AI Code Ops Dashboard

## Open Candidates

unexpected free-form text

## In Progress

No items.

## Merge Requests Opened

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
