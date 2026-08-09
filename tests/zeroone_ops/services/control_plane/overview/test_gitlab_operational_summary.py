from datetime import UTC, datetime

import pytest

from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemSourceRef, WorkItemState
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_builder import (
    GitLabOperationalSummaryBuilder,
)
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_renderer import (
    GitLabOperationalSummaryRenderer,
)
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_service import (
    GitLabOperationalSummaryService,
)
from zeroone_ops.services.control_plane.overview.gitlab_operational_summary_store import (
    GitLabOperationalSummaryStore,
)
from zeroone_ops.services.control_plane.overview.operational_summary_models import (
    FindingSyncObservation,
    OperationalSummaryView,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)


class FakeGitLabIssueClient:
    def __init__(self) -> None:
        self.issues: list[GitLabIssueInfo] = []
        self.create_count = 0
        self.update_count = 0
        self.find_labels: list[str] | None = None

    def list_open_issues(
        self,
        *,
        project_id: str,
        labels: list[str] | None = None,
    ) -> list[GitLabIssueInfo]:
        assert project_id == "group/project"
        self.find_labels = labels
        return self.issues

    def create_issue(
        self,
        *,
        project_id: str,
        title: str,
        description: str,
        labels: list[str],
    ) -> GitLabIssueInfo:
        assert project_id == "group/project"
        assert labels == ["zeroone-summary"]
        self.create_count += 1
        issue = _issue(iid=10, title=title, description=description)
        self.issues = [issue]
        return issue

    def update_issue(
        self,
        *,
        project_id: str,
        issue_iid: int,
        title: str,
        description: str,
        labels: list[str],
    ) -> GitLabIssueInfo:
        assert project_id == "group/project"
        assert issue_iid == 10
        assert title == "ZeroOne Ops Summary"
        assert labels == ["zeroone-summary"]
        self.update_count += 1
        issue = _issue(iid=10, title=title, description=description)
        self.issues = [issue]
        return issue


def test_renderer_uses_gitlab_merge_request_vocabulary() -> None:
    body = GitLabOperationalSummaryRenderer().render(
        OperationalSummaryView(
            policy_issue_url=None,
            work_item_counts={},
            active_change_requests=[],
            recent_outcomes=[],
            latest_finding_sync=None,
            active_change_requests_omitted_count=1,
        )
    )

    assert "## Active Remediation MRs" in body
    assert "No active remediation merge requests." in body
    assert "pull request" not in body


def test_builder_normalizes_linked_gitlab_merge_requests() -> None:
    result = GitLabWorkItemLookupResult(
        issue=_issue(iid=20, title="ZeroOne Ops: SIM103", description=""),
        work_item=WorkItemState(
            work_item_id="work-1",
            kind="remediation",
            status="in_progress",
            source=WorkItemSourceRef(source="ruff-sarif", source_item_key="sim103"),
            summary="Return the condition directly.",
            linked_change_request=ChangeRequestRef(
                number=12,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/12",
            ),
        ),
    )

    view = GitLabOperationalSummaryBuilder().build(
        work_items=[result],
        policy_issue_url=None,
        latest_finding_sync=None,
    )

    assert view.work_item_counts["in_progress"] == 1
    assert view.active_change_requests[0].web_url.endswith("/merge_requests/12")


def test_store_uses_exact_title_and_label_and_rejects_duplicates() -> None:
    client = FakeGitLabIssueClient()
    store = GitLabOperationalSummaryStore(client)  # type: ignore[arg-type]

    assert store.find_open_issue(scope_id="group/project") is None
    assert client.find_labels == ["zeroone-summary"]

    client.issues = [
        _issue(iid=1, title="ZeroOne Ops Summary", description="one"),
        _issue(iid=2, title="ZeroOne Ops Summary", description="two"),
    ]
    with pytest.raises(GitLabClientError, match="Ambiguous GitLab operational summary"):
        store.find_open_issue(scope_id="group/project")


def test_service_creates_updates_and_preserves_prior_finding_sync() -> None:
    client = FakeGitLabIssueClient()
    service = GitLabOperationalSummaryService(
        store=GitLabOperationalSummaryStore(client)  # type: ignore[arg-type]
    )
    observation = FindingSyncObservation(
        observed_at=datetime(2026, 8, 9, 12, 0, tzinfo=UTC),
        total_findings=3,
        promoted_findings=2,
        backlog_only_findings=1,
        severity_counts={"high": 2, "medium": 1},
        backlog_reason_counts={"severity_disabled": 1},
    )

    created = service.publish(
        project_id="group/project",
        work_items=[],
        policy_issue_url="https://gitlab.example.com/group/project/-/issues/1",
        latest_finding_sync=observation,
    )
    unchanged = service.publish(
        project_id="group/project",
        work_items=[],
        policy_issue_url="https://gitlab.example.com/group/project/-/issues/1",
        latest_finding_sync=None,
    )
    updated = service.publish(
        project_id="group/project",
        work_items=[],
        policy_issue_url=None,
        latest_finding_sync=None,
    )

    assert (created.action, unchanged.action, updated.action) == ("created", "unchanged", "updated")
    assert client.create_count == 1
    assert client.update_count == 1
    assert client.issues[0].description.count("- Findings: `3`") == 1


def _issue(*, iid: int, title: str, description: str) -> GitLabIssueInfo:
    return GitLabIssueInfo(
        id=iid,
        iid=iid,
        web_url=f"https://gitlab.example.com/group/project/-/issues/{iid}",
        title=title,
        description=description,
    )
