from datetime import UTC, datetime

from zeroone_ops.models.dashboard import DashboardDocument, DashboardItem, empty_sections
from zeroone_ops.models.review import ChangeRequestReviewCandidate, ReviewResult
from zeroone_ops.services.review.review_dashboard_updater import ReviewDashboardUpdater


class FakeDashboardService:
    def __init__(self, existing_items: list[DashboardItem] | None = None) -> None:
        self.existing_items = existing_items or []
        self.items: list[DashboardItem] = []

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        assert project_id == "123"
        sections = empty_sections()
        sections[0].items = list(self.existing_items)
        return DashboardDocument(
            issue_id=11,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Work Queue",
            sections=sections,
        )

    def upsert_items(self, *, project_id: str, items: list[DashboardItem]) -> DashboardDocument:
        assert project_id == "123"
        self.items = items
        sections = empty_sections()
        sections[0].items = list(items)
        return DashboardDocument(
            issue_id=11,
            issue_iid=11,
            issue_url="https://gitlab.example.com/group/project/-/issues/11",
            title="AI Code Ops Work Queue",
            sections=sections,
        )


def build_merge_request() -> ChangeRequestReviewCandidate:
    return ChangeRequestReviewCandidate(
        iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )


def build_remediation_item() -> DashboardItem:
    return DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="sonarqube",
        status="mr_opened",
        title="python:S123 in src/app.py",
        summary="Open remediation merge request",
        priority="high",
        source_reference="AX123",
        file="src/app.py",
        rule="python:S123",
        merge_request_iid=17,
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        commit_sha="before123",
    )


def test_update_enriches_linked_remediation_item() -> None:
    dashboard_service = FakeDashboardService(existing_items=[build_remediation_item()])
    updater = ReviewDashboardUpdater(dashboard_service)

    result = updater.update(
        project_id="123",
        merge_request=build_merge_request(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="Ordering changed in a shared path.",
            follow_up_lines=["Follow-up review after the earlier bot pass on `abc123`."],
            review_confidence=0.78,
            review_confidence_reason="The diff shows a concrete behavior change.",
            findings=[],
        ),
    )

    assert result.dashboard_issue_url is not None
    assert result.error_message is None
    assert len(dashboard_service.items) == 1
    item = dashboard_service.items[0]
    assert item.id == "sonar:AX123"
    assert item.type == "sonarqube"
    assert item.review_status == "findings_present"
    assert item.review_findings_count == 0
    assert item.review_feedback_summary == "Ordering changed in a shared path."
    assert item.review_follow_up_lines == [
        "Follow-up review after the earlier bot pass on `abc123`."
    ]
    assert item.review_confidence == 0.78
    assert item.review_confidence_reason == "The diff shows a concrete behavior change."
    assert item.reviewed_head_sha == "abc123"
    assert item.commit_sha == "abc123"
    assert isinstance(item.review_feedback_updated_at, datetime)
    assert item.review_feedback_updated_at.tzinfo == UTC


def test_update_writes_fallback_review_status_item_when_no_link_exists() -> None:
    dashboard_service = FakeDashboardService()
    updater = ReviewDashboardUpdater(dashboard_service)

    result = updater.update(
        project_id="123",
        merge_request=build_merge_request(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
            follow_up_lines=["Follow-up review after the earlier bot pass on `abc123`."],
            review_confidence=0.78,
            review_confidence_reason="The finding is grounded in a narrow changed diff.",
            findings=[],
        ),
    )

    assert result.dashboard_issue_url is not None
    assert result.error_message is None
    assert len(dashboard_service.items) == 1
    item = dashboard_service.items[0]
    assert item.id == "mr-review:17:abc123"
    assert item.source == "pull_request_review"
    assert item.type == "review_status"
    assert item.review_status == "findings_present"
    assert item.review_findings_count == 0
    assert item.review_feedback_summary == "One medium-risk finding."
    assert item.review_follow_up_lines == [
        "Follow-up review after the earlier bot pass on `abc123`."
    ]
    assert "Follow-up review after the earlier bot pass on `abc123`." in item.summary
    assert "Review confidence: 0.78." in item.summary


def test_update_returns_error_message_when_dashboard_write_fails() -> None:
    class FailingDashboardService:
        def load_or_create(self, *, project_id: str) -> DashboardDocument:
            del project_id
            raise RuntimeError("boom")

    updater = ReviewDashboardUpdater(FailingDashboardService())

    result = updater.update(
        project_id="123",
        merge_request=build_merge_request(),
        review_result=ReviewResult(
            classification="no_findings",
            summary="No findings.",
            findings=[],
        ),
    )

    assert result.dashboard_issue_url is None
    assert result.error_message == "Dashboard mirror failed: boom"


def test_update_uses_clear_summary_for_manual_review_only() -> None:
    dashboard_service = FakeDashboardService()
    updater = ReviewDashboardUpdater(dashboard_service)

    result = updater.update(
        project_id="123",
        merge_request=build_merge_request(),
        review_result=ReviewResult(
            classification="manual_review_only",
            summary="The available context was insufficient.",
            follow_up_lines=["Follow-up review after the earlier bot pass on `abc123`."],
            review_confidence=0.31,
            review_confidence_reason="The diff is too broad for a reliable review judgment.",
            findings=[],
        ),
    )

    assert result.error_message is None
    item = dashboard_service.items[0]
    assert item.review_status == "manual_review_only"
    assert "Bot assessment was insufficient for a trustworthy review decision." in item.summary
    assert "Follow-up review after the earlier bot pass on `abc123`." in item.summary
    assert "Review confidence: 0.31." in item.summary
