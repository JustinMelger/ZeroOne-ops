from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.remediation import RemediationExecutionTarget, RemediationWorkItem
from zeroone_ops.services.control_plane.github_work_item_service import (
    GitHubWorkItemService,
)
from zeroone_ops.services.control_plane.remediation_work_item_promotion_service import (
    RemediationWorkItemPromotionContext,
)
from zeroone_ops.services.remediation.control_plane import GitHubRemediationControlPlane


def build_work_item() -> RemediationWorkItem:
    return RemediationWorkItem(
        dashboard_item_id="sonar:AX123",
        source_type="sonarqube",
        source_ref="AX123",
        title="Remediate Sonar issue AX123 in src/api.py",
        status="open",
        message="Fix the issue.",
        file_path="src/api.py",
        line=42,
        severity="high",
    )


def build_execution_target() -> RemediationExecutionTarget:
    return RemediationExecutionTarget(
        item_id="sonar:AX123",
        source_type="sonarqube",
        source_ref="AX123",
        title="Remediate Sonar issue AX123 in src/api.py",
        status="open",
        message="Fix the issue.",
        file_path="src/api.py",
        line=42,
        severity="high",
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
            id=len(self.issues) + 1,
            number=len(self.issues) + 10,
            web_url="https://github.example.com/octo-org/octo-repo/issues/10",
            title=title,
            body=body,
        )
        self.issues.append(issue)
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
        del repository_id, labels
        issue = GitHubIssueInfo(
            id=issue_number,
            number=issue_number,
            web_url=f"https://github.example.com/octo-org/octo-repo/issues/{issue_number}",
            title=title,
            body=body,
        )
        self.issues = [issue]
        return issue


def test_materialize_promoted_work_item_creates_approved_github_issue() -> None:
    client = FakeGitHubWorkItemClient()
    control_plane = GitHubRemediationControlPlane(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
        repository_id="octo-org/octo-repo",
    )

    materialized = control_plane.materialize_promoted_work_item(
        work_item=build_work_item(),
        promotion_context=RemediationWorkItemPromotionContext(selected_for_remediation=True),
    )

    assert materialized is not None
    assert materialized.status == "approved"
    assert materialized.source.source_item_key == "AX123"
    assert len(client.issues) == 1


def test_materialize_promoted_work_item_skips_backlog_only_candidates() -> None:
    client = FakeGitHubWorkItemClient()
    control_plane = GitHubRemediationControlPlane(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
        repository_id="octo-org/octo-repo",
    )

    materialized = control_plane.materialize_promoted_work_item(
        work_item=build_work_item(),
        promotion_context=RemediationWorkItemPromotionContext(),
    )

    assert materialized is None
    assert client.issues == []


def test_mark_publish_started_reuses_promoted_work_item_identity() -> None:
    client = FakeGitHubWorkItemClient()
    control_plane = GitHubRemediationControlPlane(
        work_item_service=GitHubWorkItemService(client),  # type: ignore[arg-type]
        repository_id="octo-org/octo-repo",
    )

    promoted = control_plane.materialize_promoted_work_item(
        work_item=build_work_item(),
        promotion_context=RemediationWorkItemPromotionContext(selected_for_remediation=True),
    )
    assert promoted is not None

    in_progress = control_plane.mark_publish_started(
        selected_issue=build_execution_target(),
    )

    assert in_progress.work_item_id == promoted.work_item_id
    assert in_progress.status == "in_progress"
    assert len(client.issues) == 1
