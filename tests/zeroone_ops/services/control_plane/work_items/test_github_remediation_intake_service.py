from datetime import UTC, datetime

from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.control_plane.work_items.github_remediation_intake_service import (
    GitHubRemediationIntakeService,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lookup_service import (
    GitHubWorkItemLookupResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_upsert_service import (
    GitHubWorkItemUpsertResult,
)

from .test_support import build_work_item


class FakeGitHubWorkItemService:
    """Capture authoritative work-item reads and claims for intake tests."""

    def __init__(self, items: list[GitHubWorkItemLookupResult]) -> None:
        self.items = items
        self.upserted_work_items: list[WorkItemState] = []

    def list_open_work_items(
        self,
        *,
        repository_id: str,
    ) -> list[GitHubWorkItemLookupResult]:
        del repository_id
        return list(self.items)

    def upsert_work_item(
        self,
        *,
        repository_id: str,
        work_item: WorkItemState,
    ) -> GitHubWorkItemUpsertResult:
        del repository_id
        self.upserted_work_items.append(work_item)
        existing = next(
            item for item in self.items if item.work_item.identity_key == work_item.identity_key
        )
        claimed = GitHubWorkItemLookupResult(issue=existing.issue, work_item=work_item)
        self.items = [
            claimed if item.work_item.identity_key == work_item.identity_key else item
            for item in self.items
        ]
        return GitHubWorkItemUpsertResult(
            issue=existing.issue,
            action="updated",
            work_item=work_item,
        )


def _lookup_result(
    *,
    number: int,
    created_at: datetime,
    work_item: WorkItemState,
) -> GitHubWorkItemLookupResult:
    return GitHubWorkItemLookupResult(
        issue=GitHubIssueInfo(
            id=number,
            number=number,
            web_url=f"https://github.example.com/octo-org/octo-repo/issues/{number}",
            title=work_item.summary,
            body="machine state",
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
    service = GitHubRemediationIntakeService(
        work_item_service=FakeGitHubWorkItemService(  # type: ignore[arg-type]
            [
                _lookup_result(
                    number=12,
                    created_at=datetime(2026, 7, 3, tzinfo=UTC),
                    work_item=low,
                ),
                _lookup_result(
                    number=13,
                    created_at=datetime(2026, 7, 3, tzinfo=UTC),
                    work_item=high,
                ),
                _lookup_result(
                    number=11,
                    created_at=datetime(2026, 7, 1, tzinfo=UTC),
                    work_item=older_medium,
                ),
            ]
        )
    )

    result = service.select_and_claim(repository_id="octo-org/octo-repo")

    assert result.selected_target is not None
    assert result.selected_target.item_id == "work-high"
    assert result.claimed_work_item is not None
    assert result.claimed_work_item.status == "in_progress"


def test_select_and_claim_uses_issue_number_after_equal_creation_times() -> None:
    first = _with_identity(
        build_work_item(status="approved"),
        work_item_id="work-first",
    ).model_copy(update={"severity": "medium"})
    second = _with_identity(
        build_work_item(status="approved"),
        work_item_id="work-second",
    ).model_copy(update={"severity": "medium"})
    created_at = datetime(2026, 7, 3, tzinfo=UTC)
    service = GitHubRemediationIntakeService(
        work_item_service=FakeGitHubWorkItemService(  # type: ignore[arg-type]
            [
                _lookup_result(number=12, created_at=created_at, work_item=second),
                _lookup_result(number=11, created_at=created_at, work_item=first),
            ]
        )
    )

    result = service.select_and_claim(repository_id="octo-org/octo-repo")

    assert result.selected_target is not None
    assert result.selected_target.item_id == "work-first"


def test_select_and_claim_skips_linked_or_incomplete_work_items() -> None:
    linked = _with_identity(
        build_work_item(status="approved"),
        work_item_id="work-linked",
    ).model_copy(
        update={
            "linked_change_request": ChangeRequestRef(number=10, web_url="https://github/x/10"),
        }
    )
    missing_path = _with_identity(
        build_work_item(status="approved"),
        work_item_id="work-missing-path",
    ).model_copy(update={"file_path": None})
    escaping_path = _with_identity(
        build_work_item(status="approved"),
        work_item_id="work-escaping-path",
    ).model_copy(update={"file_path": "../outside.py"})
    service = GitHubRemediationIntakeService(
        work_item_service=FakeGitHubWorkItemService(  # type: ignore[arg-type]
            [
                _lookup_result(
                    number=10,
                    created_at=datetime(2026, 7, 1, tzinfo=UTC),
                    work_item=linked,
                ),
                _lookup_result(
                    number=11,
                    created_at=datetime(2026, 7, 2, tzinfo=UTC),
                    work_item=missing_path,
                ),
                _lookup_result(
                    number=12,
                    created_at=datetime(2026, 7, 3, tzinfo=UTC),
                    work_item=escaping_path,
                ),
            ]
        )
    )

    result = service.select_and_claim(repository_id="octo-org/octo-repo")

    assert result.selected_target is None
    assert result.claimed_work_item is None
    assert result.item_count == 3
    assert result.message == "No eligible approved GitHub remediation work items were found."


def test_select_and_claim_dry_run_does_not_claim_the_work_item() -> None:
    work_item = _with_identity(
        build_work_item(status="approved"),
        work_item_id="work-dry-run",
    )
    fake_service = FakeGitHubWorkItemService(
        [
            _lookup_result(
                number=11,
                created_at=datetime(2026, 7, 3, tzinfo=UTC),
                work_item=work_item,
            )
        ]
    )
    service = GitHubRemediationIntakeService(
        work_item_service=fake_service,  # type: ignore[arg-type]
    )

    result = service.select_and_claim(repository_id="octo-org/octo-repo", persist=False)

    assert result.selected_target is not None
    assert result.selected_target.status == "approved"
    assert fake_service.upserted_work_items == []
