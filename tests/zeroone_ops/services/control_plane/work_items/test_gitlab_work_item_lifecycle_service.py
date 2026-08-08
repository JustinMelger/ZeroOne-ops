from datetime import UTC, datetime, timedelta

import httpx

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.work_item import ChangeRequestRef, WorkItemClaim, WorkItemState
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lifecycle_service import (
    GitLabWorkItemLifecycleService,
)

from .test_gitlab_remediation_intake_service import FakeGitLabWorkItemService, _lookup_result
from .test_support import build_work_item


class FakeChangeRequestClient:
    """Return configured GitLab merge-request state for lifecycle tests."""

    def __init__(self, state: ChangeRequestState | Exception) -> None:
        self.state = state

    def get_change_request_state(
        self,
        *,
        project_id: str,
        change_request_number: int,
    ) -> ChangeRequestState:
        del project_id, change_request_number
        if isinstance(self.state, Exception):
            raise self.state
        return self.state


def _linked_work_item(*, status: str = "in_progress") -> WorkItemState:
    return build_work_item(status=status).model_copy(
        update={
            "linked_change_request": ChangeRequestRef(
                number=21,
                web_url="https://gitlab.example.com/group/project/-/merge_requests/21",
            )
        }
    )


def _state(*, state: str) -> ChangeRequestState:
    return ChangeRequestState(
        iid=21,
        web_url="https://gitlab.example.com/group/project/-/merge_requests/21",
        source_branch="zeroone-ops/fix",
        head_sha="abc123",
        state=state,
    )


def _service(
    work_item: WorkItemState,
    change_request_state: ChangeRequestState | Exception,
) -> tuple[GitLabWorkItemLifecycleService, FakeGitLabWorkItemService]:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    fake_work_item_service = FakeGitLabWorkItemService(
        [_lookup_result(iid=11, created_at=now, work_item=work_item)]
    )
    return (
        GitLabWorkItemLifecycleService(
            work_item_service=fake_work_item_service,  # type: ignore[arg-type]
            change_request_client=FakeChangeRequestClient(change_request_state),
        ),
        fake_work_item_service,
    )


def test_reconcile_recovers_stale_unlinked_claim() -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    work_item = build_work_item(status="in_progress").model_copy(
        update={"claim": WorkItemClaim(claimed_at=now - timedelta(hours=24), run_id="run-1")}
    )
    service, fake_work_item_service = _service(work_item, _state(state="opened"))

    result = service.reconcile(project_id="group/project", now=now)

    assert result.recovered_stale_claim_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "approved"
    assert fake_work_item_service.upserted_work_items[0].claim is None


def test_reconcile_marks_open_merge_request_in_progress_and_clears_claim() -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    work_item = _linked_work_item().model_copy(
        update={"claim": WorkItemClaim(claimed_at=now, run_id="run-1")}
    )
    service, fake_work_item_service = _service(work_item, _state(state="opened"))

    result = service.reconcile(project_id="group/project", now=now)

    assert result.in_progress_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "in_progress"
    assert fake_work_item_service.upserted_work_items[0].claim is None


def test_reconcile_blocks_closed_merge_request_and_retains_link() -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    service, fake_work_item_service = _service(_linked_work_item(), _state(state="closed"))

    result = service.reconcile(project_id="group/project", now=now)

    assert result.blocked_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "blocked"
    assert fake_work_item_service.upserted_work_items[0].linked_change_request is not None


def test_reconcile_closes_native_issue_after_persisting_completed_work_item() -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    service, fake_work_item_service = _service(_linked_work_item(), _state(state="merged"))

    result = service.reconcile(project_id="group/project", now=now)

    assert result.completed_count == 1
    assert result.closed_issue_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "completed"
    assert fake_work_item_service.closed_issue_iids == [11]


def test_reconcile_keeps_terminal_issue_open_when_close_transport_fails(monkeypatch) -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    service, fake_work_item_service = _service(
        build_work_item(status="dismissed"),
        _state(state="opened"),
    )

    def fail_close(*, project_id: str, issue_iid: int) -> None:
        del project_id, issue_iid
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(fake_work_item_service, "close_work_item_issue", fail_close)

    result = service.reconcile(project_id="group/project", now=now)

    assert result.closed_issue_count == 0
    assert fake_work_item_service.closed_issue_iids == []


def test_reconcile_blocks_when_merge_request_metadata_is_inaccessible() -> None:
    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    service, fake_work_item_service = _service(
        _linked_work_item(),
        GitLabClientError("forbidden"),
    )

    result = service.reconcile(project_id="group/project", now=now)

    assert result.blocked_count == 1
    assert fake_work_item_service.upserted_work_items[0].status == "blocked"
