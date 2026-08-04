from datetime import UTC, datetime

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.services.control_plane.overview.github_operational_summary_renderer import (
    GitHubFindingSyncObservation,
)
from zeroone_ops.services.control_plane.overview.github_operational_summary_service import (
    GitHubOperationalSummaryService,
)


class FakeStore:
    def __init__(self) -> None:
        self.issue: GitHubIssueInfo | None = None

    def find_open_issue(self, *, repository_id: str) -> GitHubIssueInfo | None:
        del repository_id
        return self.issue

    def create_issue(self, *, repository_id: str, body: str) -> GitHubIssueInfo:
        self.issue = GitHubIssueInfo(
            id=1,
            number=2,
            web_url=f"https://github.example.com/{repository_id}/issues/2",
            title="Summary",
            body=body,
        )
        return self.issue

    def update_issue_body(
        self, *, repository_id: str, issue_number: int, body: str
    ) -> GitHubIssueInfo:
        del repository_id, issue_number
        assert self.issue is not None
        self.issue = self.issue.model_copy(update={"body": body})
        return self.issue


class StaticBuilder:
    def build(self, **kwargs: object) -> str:
        del kwargs
        return "view"


class StaticRenderer:
    def __init__(self, body: str) -> None:
        self.body = body

    def render(self, view: str) -> str:
        assert view == "view"
        return self.body


def test_summary_service_creates_updates_and_preserves_identical_summary() -> None:
    store = FakeStore()
    renderer = StaticRenderer("first")
    service = GitHubOperationalSummaryService(
        store=store,  # type: ignore[arg-type]
        builder=StaticBuilder(),  # type: ignore[arg-type]
        renderer=renderer,  # type: ignore[arg-type]
    )

    created = service.publish(
        repository_id="octo-org/octo-repo",
        work_items=[],
        policy_issue_url=None,
        latest_finding_sync=None,
    )
    unchanged = service.publish(
        repository_id="octo-org/octo-repo",
        work_items=[],
        policy_issue_url=None,
        latest_finding_sync=None,
    )
    renderer.body = "second"
    updated = service.publish(
        repository_id="octo-org/octo-repo",
        work_items=[],
        policy_issue_url=None,
        latest_finding_sync=None,
    )

    assert (created.action, unchanged.action, updated.action) == ("created", "unchanged", "updated")


def test_summary_service_preserves_prior_sync_observation_on_later_refresh() -> None:
    store = FakeStore()
    service = GitHubOperationalSummaryService(store=store)
    observation = GitHubFindingSyncObservation(
        observed_at=datetime(2026, 8, 4, 10, 30, tzinfo=UTC),
        total_findings=5,
        promoted_findings=2,
        backlog_only_findings=3,
        severity_counts={"high": 2, "medium": 3},
        backlog_reason_counts={"severity_disabled": 3},
    )

    service.publish(
        repository_id="octo-org/octo-repo",
        work_items=[],
        policy_issue_url=None,
        latest_finding_sync=observation,
    )
    updated = service.publish(
        repository_id="octo-org/octo-repo",
        work_items=[],
        policy_issue_url=None,
        latest_finding_sync=None,
    )

    assert updated.action == "unchanged"
    assert store.issue is not None
    assert "- Findings: `5`" in store.issue.body
