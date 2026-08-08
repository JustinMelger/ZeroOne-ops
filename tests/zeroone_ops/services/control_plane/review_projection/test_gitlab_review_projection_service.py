from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.review import ChangeRequestReviewContext, RemediationReviewContext
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.control_plane.review_projection.gitlab_review_projection_service import (
    GitLabReviewProjectionService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_upsert_service import (
    GitLabWorkItemUpsertResult,
)


def _work_item() -> WorkItemState:
    return WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="in_progress",
        source=WorkItemSourceRef(
            source="ruff-sarif",
            source_item_key="C416:src/service.py:42",
            repository_scope="group/project",
        ),
        summary="Unnecessary set comprehension.",
        severity="high",
        file_path="src/service.py",
        line=42,
        linked_change_request=ChangeRequestRef(
            number=17,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        ),
    )


def _context() -> ChangeRequestReviewContext:
    return ChangeRequestReviewContext(
        change_request_number=17,
        title="Review remediation merge request",
        source_branch="zeroone-ops/fix",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        remediation_context=RemediationReviewContext(
            source="Untrusted description value",
            source_id="untrusted-source",
            item_reference="untrusted-item",
        ),
    )


class FakeGitLabWorkItemService:
    """Keep one linked work item in memory for review-projection tests."""

    def __init__(self, work_item: WorkItemState) -> None:
        self.work_item = work_item
        self.project_ids: list[str] = []

    def find_open_work_item_by_change_request(
        self,
        *,
        project_id: str,
        change_request_number: int,
    ) -> GitLabWorkItemLookupResult | None:
        self.project_ids.append(project_id)
        if self.work_item.linked_change_request is None:
            return None
        if self.work_item.linked_change_request.number != change_request_number:
            return None
        return GitLabWorkItemLookupResult(
            issue=GitLabIssueInfo(
                id=1,
                iid=2,
                web_url="https://gitlab.example.com/group/project/-/issues/2",
                title=self.work_item.summary,
                description="machine state",
            ),
            work_item=self.work_item,
        )

    def upsert_work_item(
        self,
        *,
        project_id: str,
        work_item: WorkItemState,
    ) -> GitLabWorkItemUpsertResult:
        self.project_ids.append(project_id)
        self.work_item = work_item
        return GitLabWorkItemUpsertResult(
            issue=GitLabIssueInfo(
                id=1,
                iid=2,
                web_url="https://gitlab.example.com/group/project/-/issues/2",
                title=work_item.summary,
                description="machine state",
            ),
            action="updated",
            work_item=work_item,
        )


def test_project_review_uses_stored_gitlab_merge_request_link() -> None:
    work_item_service = FakeGitLabWorkItemService(_work_item())

    result = GitLabReviewProjectionService(work_item_service).project_review(  # type: ignore[arg-type]
        repository_id="group/project",
        context=_context(),
        classification="no_findings",
        reviewed_sha="abc123",
        review_note_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_1",
    )

    assert result.action == "updated"
    assert result.work_item is not None
    assert result.work_item.projected_review is not None
    assert result.work_item.projected_review.reviewed_sha == "abc123"
    assert result.work_item.projected_review.follow_up_required is False
    assert work_item_service.project_ids == ["group/project", "group/project"]


def test_project_review_noops_without_linked_gitlab_work_item() -> None:
    work_item_service = FakeGitLabWorkItemService(_work_item())

    result = GitLabReviewProjectionService(work_item_service).project_review(  # type: ignore[arg-type]
        repository_id="group/project",
        context=_context().model_copy(update={"change_request_number": 18}),
        classification="no_findings",
        reviewed_sha="abc123",
        review_note_url="https://gitlab.example.com/group/project/-/merge_requests/18#note_1",
    )

    assert result.action == "no_linked_work_item"
    assert result.work_item is None
