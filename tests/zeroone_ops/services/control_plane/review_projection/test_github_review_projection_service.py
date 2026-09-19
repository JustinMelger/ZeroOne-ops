from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.review import (
    ChangeRequestReviewContext,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    RemediationReviewContext,
)
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.control_plane.review_projection.github_review_projection_service import (
    GitHubReviewProjectionService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_service import (
    GitHubWorkItemService,
)


def build_work_item() -> WorkItemState:
    return WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="approved",
        source=WorkItemSourceRef(
            source="sonarqube",
            source_item_key="AX123",
            repository_scope="octo-org/octo-repo",
        ),
        summary="Remediate Sonar issue AX123 in api.py",
        severity="high",
        file_path="src/api.py",
        line=42,
        linked_change_request=ChangeRequestRef(
            number=1,
            web_url="https://github.example.com/octo-org/octo-repo/pull/1",
        ),
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


def build_actionable_artifact() -> PublishableReviewArtifact:
    return PublishableReviewArtifact(
        classification="findings_present",
        summary="The remediation misses an error path.",
        findings=[
            PublishableReviewFinding(
                severity="high",
                file_path="src/api.py",
                line_start=42,
                line_end=42,
                title="Preserve the error response.",
                evidence="The changed branch returns success for the error path.",
                explanation="The route would report success after a failure.",
                suggested_follow_up="Keep the existing error response.",
            )
        ],
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

    def list_closed_issues(
        self,
        *,
        repository_id: str,
        labels: list[str] | None = None,
    ) -> list[GitHubIssueInfo]:
        del repository_id, labels
        return []

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
        artifact=build_actionable_artifact(),
        reviewed_sha="abc123",
        review_note_id=1,
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
    )

    assert result.action == "updated"
    assert result.work_item is not None
    assert result.work_item.work_item_id == existing.work_item.work_item_id
    assert result.work_item.status == "review_feedback_required"
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

    assert result.action == "no_linked_work_item"
    assert result.work_item is None


def test_project_review_without_structured_feedback_requires_manual_follow_up() -> None:
    client = FakeGitHubWorkItemClient()
    work_item_service = GitHubWorkItemService(client)  # type: ignore[arg-type]
    work_item_service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(),
    )

    result = GitHubReviewProjectionService(work_item_service).project_review(
        repository_id="octo-org/octo-repo",
        context=build_context(),
        classification="findings_present",
        reviewed_sha="abc123",
        review_note_id=1,
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
    )

    assert result.action == "updated"
    assert result.work_item is not None
    assert result.work_item.status == "approved"
    assert result.work_item.projected_review is not None
    assert result.work_item.projected_review.classification == "manual_review_only"


def test_project_review_ignores_stale_change_request_head() -> None:
    client = FakeGitHubWorkItemClient()
    work_item_service = GitHubWorkItemService(client)  # type: ignore[arg-type]
    original = work_item_service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(),
    )
    service = GitHubReviewProjectionService(
        work_item_service,
        change_request_state_lookup=lambda number: ChangeRequestState(
            iid=number,
            web_url="https://github.example.com/octo-org/octo-repo/pull/1",
            source_branch="zeroone-ops/fix",
            head_sha="newer-sha",
            state="opened",
        ),
    )

    result = service.project_review(
        repository_id="octo-org/octo-repo",
        context=build_context(),
        artifact=build_actionable_artifact(),
        reviewed_sha="abc123",
        review_note_id=1,
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
    )

    assert result.action == "stale_review"
    assert result.work_item == original.work_item


def test_project_review_same_sha_new_note_supersedes_queued_revision() -> None:
    client = FakeGitHubWorkItemClient()
    work_item_service = GitHubWorkItemService(client)  # type: ignore[arg-type]
    work_item_service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(),
    )
    service = GitHubReviewProjectionService(work_item_service)
    first = service.project_review(
        repository_id="octo-org/octo-repo",
        context=build_context(),
        artifact=build_actionable_artifact(),
        reviewed_sha="abc123",
        review_note_id=1,
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
    )
    assert first.work_item is not None
    queued = first.work_item.model_copy(update={"status": "review_revision_queued"})
    work_item_service.upsert_work_item(repository_id="octo-org/octo-repo", work_item=queued)

    result = service.project_review(
        repository_id="octo-org/octo-repo",
        context=build_context(),
        artifact=build_actionable_artifact().model_copy(
            update={"summary": "A newer review found a different regression."}
        ),
        reviewed_sha="abc123",
        review_note_id=2,
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-2",
    )

    assert result.action == "updated"
    assert result.work_item is not None
    assert result.work_item.status == "review_feedback_required"
    assert result.work_item.review_revision_request is None
    assert result.work_item.projected_review is not None
    assert result.work_item.projected_review.review_note_reference == "github-comment-2"


def test_project_review_uses_stored_change_request_link_not_description_source() -> None:
    client = FakeGitHubWorkItemClient()
    work_item_service = GitHubWorkItemService(client)  # type: ignore[arg-type]
    work_item_service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item().model_copy(
            update={
                "source": WorkItemSourceRef(
                    source="ruff-sarif",
                    source_item_key="C416:src/service.py:42",
                    repository_scope="octo-org/octo-repo",
                )
            }
        ),
    )
    context = build_context().model_copy(
        update={
            "remediation_context": RemediationReviewContext(
                source="Untrusted source",
                source_id="untrusted-source",
                item_reference_label="Item reference",
                item_reference="untrusted-item",
            )
        }
    )

    result = GitHubReviewProjectionService(work_item_service).project_review(
        repository_id="octo-org/octo-repo",
        context=context,
        classification="no_findings",
        reviewed_sha="abc123",
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
    )

    assert result.action == "updated"
    assert result.work_item is not None
    assert result.work_item.projected_review is not None


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

    assert result.action == "no_linked_work_item"
    assert result.work_item is None


def test_project_review_preserves_repo_scoped_identity() -> None:
    client = FakeGitHubWorkItemClient()
    work_item_service = GitHubWorkItemService(client)  # type: ignore[arg-type]
    work_item_service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(),
    )

    result = GitHubReviewProjectionService(work_item_service).project_review(
        repository_id="octo-org/octo-repo",
        context=build_context(),
        classification="no_findings",
        reviewed_sha="def456",
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-2",
    )

    assert result.action == "updated"
    assert result.work_item is not None
    assert result.work_item.source.repository_scope == "octo-org/octo-repo"
    assert result.work_item.projected_review is not None
    assert result.work_item.projected_review.reviewed_sha == "def456"


def test_project_review_noops_when_existing_work_item_links_another_change_request() -> None:
    client = FakeGitHubWorkItemClient()
    work_item_service = GitHubWorkItemService(client)  # type: ignore[arg-type]
    work_item_service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item().model_copy(
            update={
                "linked_change_request": ChangeRequestRef(
                    number=2,
                    web_url="https://github.example.com/octo-org/octo-repo/pull/2",
                )
            }
        ),
    )

    result = GitHubReviewProjectionService(work_item_service).project_review(
        repository_id="octo-org/octo-repo",
        context=build_context(),
        classification="no_findings",
        reviewed_sha="def456",
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-2",
    )

    assert result.action == "no_linked_work_item"
    assert result.work_item is None


def test_project_review_survives_follow_up_status_upsert() -> None:
    client = FakeGitHubWorkItemClient()
    work_item_service = GitHubWorkItemService(client)  # type: ignore[arg-type]
    existing = work_item_service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=build_work_item(),
    )
    projected = GitHubReviewProjectionService(work_item_service).project_review(
        repository_id="octo-org/octo-repo",
        context=build_context(),
        artifact=build_actionable_artifact(),
        reviewed_sha="abc123",
        review_note_id=1,
        review_note_url="https://github.example.com/octo-org/octo-repo/pull/1#issuecomment-1",
    )
    assert projected.work_item is not None

    follow_up = work_item_service.upsert_work_item(
        repository_id="octo-org/octo-repo",
        work_item=existing.work_item.model_copy(update={"status": "in_progress"}),
    )

    assert follow_up.work_item.projected_review is not None
    assert follow_up.work_item.projected_review.classification == "findings_present"
    assert follow_up.work_item.projected_review.review_note_reference == "github-comment-1"
    assert follow_up.work_item.projected_review.feedback is not None
