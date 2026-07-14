from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.review import ChangeRequestReviewContext, RemediationReviewContext
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.github_review_projection_service import (
    GitHubReviewProjectionService,
)
from zeroone_ops.services.control_plane.github_work_item_service import GitHubWorkItemService


def build_work_item() -> WorkItemState:
    return WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="approved",
        source=WorkItemSourceRef(
            source="sonarqube",
            source_item_key="AX123",
            repository_scope=None,
        ),
        summary="Remediate Sonar issue AX123 in api.py",
        severity="high",
        file_path="src/api.py",
        line=42,
    )


def build_context() -> ChangeRequestReviewContext:
    return ChangeRequestReviewContext(
        change_request_number=1,
        title="Review remediation PR",
        source_branch="zeroone-ops/fix",
        target_branch="main",
        web_url="https://github.example.com/octo-org/octo-repo/pull/1",
        head_sha="abc123",
        remediation_context=RemediationReviewContext(
            source="SonarQube",
            item_reference_label="Issue key",
            item_reference="AX123",
        ),
    )


class FakeGitHubWorkItemClient:
    def __init__(self) -> None:
        self.issues: list[GitHubIssueInfo] = []

    def list_open_issues(
        self,
        *,
        repository_id: str,
        labels: list[str] | None = None,
    ) -> list[GitHubIssueInfo]:
        del repository_id, labels
        return list(self.issues)

    def create_issue(
        self,
        *,
        repository_id: str,
        title: str,
        body: str,
        labels: list[str],
    ) -> GitHubIssueInfo:
        del repository_id, labels
        issue = GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=title,
            body=body,
        )
        self.issues = [issue]
        return issue

    def update_issue(
        self,
        *,
        repository_id: str,
        issue_number: int,
        title: str,
        body: str,
        labels: list[str],
    ) -> GitHubIssueInfo:
        del repository_id, issue_number, labels
        issue = GitHubIssueInfo(
            id=10,
            number=11,
            web_url="https://github.example.com/octo-org/octo-repo/issues/11",
            title=title,
            body=body,
        )
        self.issues = [issue]
        return issue


def test_project_review_updates_existing_promoted_work_item() -> None:
    client = FakeGitHubWorkItemClient()
    work_item_service = GitHubWorkItemService(client)  # type: ignore[arg-type]
    existing = work_item_service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(),
    )

    result = GitHubReviewProjectionService(work_item_service).project_review(
        repository_id="octo-org/octo-repo",
        context=build_context(),
        classification="findings_present",
        reviewed_sha="abc123",
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
    )

    assert result.action == "updated"
    assert result.work_item is not None
    assert result.work_item.work_item_id == existing.work_item.work_item_id
    assert result.work_item.status == "approved"
    assert result.work_item.projected_review is not None
    assert result.work_item.projected_review.classification == "findings_present"
    assert result.work_item.projected_review.reviewed_sha == "abc123"
    assert result.work_item.projected_review.follow_up_required is True


def test_project_review_noops_without_matching_work_item() -> None:
    client = FakeGitHubWorkItemClient()
    work_item_service = GitHubWorkItemService(client)  # type: ignore[arg-type]

    result = GitHubReviewProjectionService(work_item_service).project_review(
        repository_id="octo-org/octo-repo",
        context=build_context(),
        classification="no_findings",
        reviewed_sha="abc123",
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
    )

    assert result.action == "no_matching_work_item"
    assert result.work_item is None


def test_project_review_noops_without_remediation_context() -> None:
    client = FakeGitHubWorkItemClient()
    work_item_service = GitHubWorkItemService(client)  # type: ignore[arg-type]

    result = GitHubReviewProjectionService(work_item_service).project_review(
        repository_id="octo-org/octo-repo",
        context=ChangeRequestReviewContext(
            change_request_number=1,
            title="Normal review PR",
            source_branch="feature/x",
            target_branch="main",
            web_url="https://github.example.com/octo-org/octo-repo/pull/1",
            head_sha="abc123",
        ),
        classification="no_findings",
        reviewed_sha="abc123",
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
    )

    assert result.action == "no_remediation_context"
    assert result.work_item is None
