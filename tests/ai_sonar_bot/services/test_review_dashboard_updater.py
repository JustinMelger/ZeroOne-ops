from ai_sonar_bot.models.review import MergeRequestReviewCandidate, ReviewResult
from ai_sonar_bot.services.review_dashboard_updater import ReviewDashboardUpdater


class FakeDashboardDocument:
    def __init__(self, issue_url: str) -> None:
        self.issue_url = issue_url


class FakeDashboardService:
    def __init__(self) -> None:
        self.items = []

    def upsert_items(self, *, project_id: str, items: list) -> FakeDashboardDocument:
        assert project_id == "123"
        self.items = items
        return FakeDashboardDocument("https://gitlab.example.com/group/project/-/issues/11")


def build_merge_request() -> MergeRequestReviewCandidate:
    return MergeRequestReviewCandidate(
        iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )


def test_update_writes_one_review_status_dashboard_item() -> None:
    dashboard_service = FakeDashboardService()
    updater = ReviewDashboardUpdater(dashboard_service)

    result = updater.update(
        project_id="123",
        merge_request=build_merge_request(),
        review_result=ReviewResult(
            classification="findings_present",
            summary="One medium-risk finding.",
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


def test_update_returns_error_message_when_dashboard_write_fails() -> None:
    class FailingDashboardService:
        def upsert_items(self, *, project_id: str, items: list) -> FakeDashboardDocument:
            del project_id, items
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
