from datetime import UTC, datetime, timedelta

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemClaim, WorkItemState
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.services.control_plane.work_items.github_work_item_lifecycle_service import (
    GitHubWorkItemLifecycleService,
)

from .test_github_remediation_intake_service import FakeGitHubWorkItemService, _lookup_result
from .test_support import build_work_item


class FakeChangeRequestClient:
    """Return configured GitHub pull-request state for lifecycle tests."""

    def __init__(self, state: ChangeRequestState | Exception) -> None:
        self.state = state

    def get_change_request_state(
        self,
        *,
        repository_id: str,
        change_request_number: int,
    ) -> ChangeRequestState:
        del repository_id, change_request_number
        if isinstance(self.state, Exception):
            raise self.state
        return self.state


def _linked_work_item(*, status: str = "in_progress") -> WorkItemState:
    return build_work_item(status=status).model_copy(
        update={
            "linked_change_request": ChangeRequestRef(
                number=21,
                web_url="https://github.example.com/octo-org/octo-repo/pull/21",
            )
        }
    )


def _state(*, state: str) -> ChangeRequestState:
    return ChangeRequestState(
        iid=21,
        web_url="https://github.example.com/octo-org/octo-repo/pull/21",
        source_branch="zeroone-ops/fix",
        head_sha="abc123",
        state=state,
    )


def _service(
    work_item: WorkItemState,
    change_request_state: ChangeRequestState | Exception,
) -> tuple[GitHubWorkItemLifecycleService, FakeGitHubWorkItemService]:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    fake_work_item_service = FakeGitHubWorkItemService(
        [_lookup_result(number=11, created_at=now, work_item=work_item)]
    )
    return (
        GitHubWorkItemLifecycleService(
            work_item_service=fake_work_item_service,  # type: ignore[arg-type]
            change_request_client=FakeChangeRequestClient(change_request_state),
        ),
        fake_work_item_service,
    )


def test_reconcile_recovers_stale_unlinked_claim() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    work_item = build_work_item(status="in_progress").model_copy(
        update={"claim": WorkItemClaim(claimed_at=now - timedelta(hours=24), run_id="run-1")}
    )
    service, fake_work_item_service = _service(work_item, _state(state="opened"))

    result = service.reconcile(
        repository_id="octo-org/octo-repo",
        active_source_keys=set(),
        managed_source_ids=set(),
        now=now,
    )

    assert result.recovered_stale_claim_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "approved"
    assert fake_work_item_service.upserted_work_items[0].claim is None


def test_reconcile_marks_open_pull_request_in_progress_and_clears_claim() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    work_item = _linked_work_item().model_copy(
        update={"claim": WorkItemClaim(claimed_at=now, run_id="run-1")}
    )
    service, fake_work_item_service = _service(work_item, _state(state="opened"))

    result = service.reconcile(
        repository_id="octo-org/octo-repo",
        active_source_keys=set(),
        managed_source_ids={"sonarqube"},
        now=now,
    )

    assert result.in_progress_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "in_progress"
    assert fake_work_item_service.upserted_work_items[0].claim is None


def test_reconcile_reopens_closed_pull_request_when_finding_remains_active() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    work_item = _linked_work_item()
    service, fake_work_item_service = _service(work_item, _state(state="closed"))

    result = service.reconcile(
        repository_id="octo-org/octo-repo",
        active_source_keys={("sonarqube", "AX123")},
        managed_source_ids={"sonarqube"},
        now=now,
    )

    assert result.reopened_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "approved"
    assert fake_work_item_service.upserted_work_items[0].linked_change_request is None


def test_reconcile_completes_closed_pull_request_when_finding_is_inactive() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    work_item = _linked_work_item()
    service, fake_work_item_service = _service(work_item, _state(state="closed"))

    result = service.reconcile(
        repository_id="octo-org/octo-repo",
        active_source_keys=set(),
        managed_source_ids={"sonarqube"},
        now=now,
    )

    assert result.completed_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "completed"
    assert fake_work_item_service.upserted_work_items[0].linked_change_request is None


def test_reconcile_blocks_closed_pull_request_without_complete_source_inventory() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    work_item = _linked_work_item()
    service, fake_work_item_service = _service(work_item, _state(state="closed"))

    result = service.reconcile(
        repository_id="octo-org/octo-repo",
        active_source_keys={("sonarqube", "AX123")},
        managed_source_ids=set(),
        now=now,
    )

    assert result.blocked_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "blocked"
    assert fake_work_item_service.upserted_work_items[0].linked_change_request is not None


def test_reconcile_blocks_and_retains_link_when_pull_request_metadata_is_inaccessible() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    work_item = _linked_work_item()
    service, fake_work_item_service = _service(work_item, GitHubClientError("forbidden"))

    result = service.reconcile(
        repository_id="octo-org/octo-repo",
        active_source_keys=set(),
        managed_source_ids={"sonarqube"},
        now=now,
    )

    assert result.blocked_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "blocked"
    assert fake_work_item_service.upserted_work_items[0].linked_change_request is not None


def test_reconcile_blocks_and_retains_link_for_unsupported_pull_request_state() -> None:
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    work_item = _linked_work_item()
    service, fake_work_item_service = _service(work_item, _state(state="unknown"))

    result = service.reconcile(
        repository_id="octo-org/octo-repo",
        active_source_keys=set(),
        managed_source_ids={"sonarqube"},
        now=now,
    )

    assert result.blocked_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "blocked"
    assert fake_work_item_service.upserted_work_items[0].linked_change_request is not None
