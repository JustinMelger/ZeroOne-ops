from datetime import UTC, datetime

from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.work_items.gitlab_remediation_intake_service import (
    GitLabRemediationIntakeService,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lookup_service import (
    GitLabWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_upsert_service import (
    GitLabWorkItemUpsertResult,
)

from .test_support import build_work_item


class FakeGitLabWorkItemService:
    """Capture authoritative work-item reads and claims for intake tests."""

    def __init__(self, items: list[GitLabWorkItemLookupResult]) -> None:
        self.items = items
        self.upserted_work_items: list[WorkItemState] = []
        self.closed_issue_iids: list[int] = []

    def list_open_work_items(self, *, project_id: str) -> list[GitLabWorkItemLookupResult]:
        del project_id
        return list(self.items)

    def upsert_work_item(
        self,
        *,
        project_id: str,
        work_item: WorkItemState,
    ) -> GitLabWorkItemUpsertResult:
        del project_id
        self.upserted_work_items.append(work_item)
        existing = next(
            item for item in self.items if item.work_item.identity_key == work_item.identity_key
        )
        claimed = GitLabWorkItemLookupResult(issue=existing.issue, work_item=work_item)
        self.items = [
            claimed if item.work_item.identity_key == work_item.identity_key else item
            for item in self.items
        ]
        return GitLabWorkItemUpsertResult(
            issue=existing.issue,
            action="updated",
            work_item=work_item,
        )

    def close_work_item_issue(self, *, project_id: str, issue_iid: int) -> None:
        del project_id
        self.closed_issue_iids.append(issue_iid)


def _lookup_result(
    *,
    iid: int,
    created_at: datetime,
    work_item: WorkItemState,
) -> GitLabWorkItemLookupResult:
    return GitLabWorkItemLookupResult(
        issue=GitLabIssueInfo(
            id=iid,
            iid=iid,
            web_url=f"https://gitlab.example.com/group/project/-/issues/{iid}",
            title=work_item.summary,
            description="machine state",
            created_at=created_at,
        ),
        work_item=work_item,
    )


def _with_identity(work_item: WorkItemState, *, work_item_id: str) -> WorkItemState:
    """Give one test work item a distinct authoritative source identity."""
    return work_item.model_copy(
        update={
            "work_item_id": work_item_id,
            "source": WorkItemSourceRef(
                source=work_item.source.source,
                source_item_key=work_item_id,
                repository_scope=work_item.source.repository_scope,
            ),
        }
    )


def test_select_and_claim_prioritizes_severity_then_creation_time() -> None:
    low = _with_identity(build_work_item(status="approved"), work_item_id="work-low").model_copy(
        update={"severity": "low"}
    )
    high = _with_identity(build_work_item(status="approved"), work_item_id="work-high").model_copy(
        update={"severity": "high"}
    )
    older_medium = _with_identity(
        build_work_item(status="approved"),
        work_item_id="work-medium-old",
    ).model_copy(update={"severity": "medium"})
    claimed_at = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
    service = GitLabRemediationIntakeService(
        work_item_service=FakeGitLabWorkItemService(  # type: ignore[arg-type]
            [
                _lookup_result(
                    iid=12,
                    created_at=datetime(2026, 8, 6, tzinfo=UTC),
                    work_item=low,
                ),
                _lookup_result(
                    iid=13,
                    created_at=datetime(2026, 8, 6, tzinfo=UTC),
                    work_item=high,
                ),
                _lookup_result(
                    iid=11,
                    created_at=datetime(2026, 8, 5, tzinfo=UTC),
                    work_item=older_medium,
                ),
            ]
        ),
        clock=lambda: claimed_at,
    )

    result = service.select_and_claim(project_id="group/project", run_id="run-123")

    assert result.selected_target is not None
    assert result.selected_target.item_id == "work-high"
    assert result.claimed_work_item is not None
    assert result.claimed_work_item.status == "in_progress"
    assert result.claimed_work_item.claim is not None
    assert result.claimed_work_item.claim.claimed_at == claimed_at
    assert result.claimed_work_item.claim.run_id == "run-123"


def test_select_and_claim_skips_linked_or_unsafe_work_items() -> None:
    linked = _with_identity(
        build_work_item(status="approved"),
        work_item_id="work-linked",
    ).model_copy(
        update={
            "linked_change_request": ChangeRequestRef(number=10, web_url="https://gitlab/x/10"),
        }
    )
    escaping_path = _with_identity(
        build_work_item(status="approved"),
        work_item_id="work-escaping-path",
    ).model_copy(update={"file_path": "../outside.py"})
    service = GitLabRemediationIntakeService(
        work_item_service=FakeGitLabWorkItemService(  # type: ignore[arg-type]
            [
                _lookup_result(
                    iid=10,
                    created_at=datetime(2026, 8, 5, tzinfo=UTC),
                    work_item=linked,
                ),
                _lookup_result(
                    iid=11,
                    created_at=datetime(2026, 8, 6, tzinfo=UTC),
                    work_item=escaping_path,
                ),
            ]
        )
    )

    result = service.select_and_claim(project_id="group/project")

    assert result.selected_target is None
    assert result.claimed_work_item is None
    assert result.item_count == 2
    assert result.message == "No eligible approved GitLab remediation work items were found."


def test_select_and_claim_dry_run_does_not_claim_the_work_item() -> None:
    work_item = _with_identity(
        build_work_item(status="approved"),
        work_item_id="work-dry-run",
    )
    fake_service = FakeGitLabWorkItemService(
        [
            _lookup_result(
                iid=11,
                created_at=datetime(2026, 8, 6, tzinfo=UTC),
                work_item=work_item,
            )
        ]
    )
    service = GitLabRemediationIntakeService(
        work_item_service=fake_service,  # type: ignore[arg-type]
    )

    result = service.select_and_claim(project_id="group/project", persist=False)

    assert result.selected_target is not None
    assert result.selected_target.status == "approved"
    assert fake_service.upserted_work_items == []
