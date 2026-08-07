from dataclasses import replace
from datetime import UTC, datetime

from zeroone_ops.models.work_item import (
    PublicationRetryState,
    RecoveryAction,
    WorkItemExecutionFailure,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.remediation.recovery.recovery_decision_service import (
    RecoveryDecisionService,
    RecoveryRequest,
)


def build_work_item(*, status: str = "approved") -> WorkItemState:
    return WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status=status,  # type: ignore[arg-type]
        source=WorkItemSourceRef(
            source="ruff-sarif",
            source_item_key="src/api.py::lint_fix::SIM103",
            repository_scope="octo-org/octo-repo",
        ),
        summary="Return the condition directly.",
        severity="high",
        file_path="src/api.py",
        line=42,
    )


def build_request(
    *,
    work_item_status: str = "blocked",
    action: RecoveryAction = "retry",
    reason: str | None = None,
) -> tuple[RecoveryDecisionService, RecoveryRequest]:
    service = RecoveryDecisionService()
    work_item = build_work_item(status=work_item_status)
    return service, RecoveryRequest(
        action=action,
        actor="operator",
        request_reference="comment-42",
        expected_state_fingerprint=service.state_fingerprint(work_item),
        occurred_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
        reason=reason,
    )


def test_dismiss_records_durable_recovery_history() -> None:
    service, request = build_request(action="dismiss", reason="Not worth automating.")
    work_item = build_work_item(status="blocked")

    decision = service.decide(work_item=work_item, request=request, policy_eligible=False)

    assert decision.accepted is True
    assert decision.plan is None
    assert decision.work_item.status == "dismissed"
    assert decision.work_item.attempt_number == 1
    assert decision.work_item.recovery_events[0].reason == "Not worth automating."
    assert decision.work_item.recovery_events[0].previous_status == "blocked"


def test_retry_selects_publication_only_path_when_recorded_branch_is_available() -> None:
    service = RecoveryDecisionService()
    work_item = build_work_item(status="blocked").model_copy(
        update={
            "publication_retry": PublicationRetryState(
                branch_name="zeroone-ops/fix",
                commit_sha="abc123",
                reason="change_request_publish_failed",
            )
        }
    )
    request = RecoveryRequest(
        action="retry",
        actor="operator",
        request_reference="comment-42",
        expected_state_fingerprint=service.state_fingerprint(work_item),
        occurred_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
    )

    decision = service.decide(work_item=work_item, request=request, policy_eligible=False)

    assert decision.accepted is True
    assert decision.plan == "retry_publication"
    assert decision.work_item.status == "in_progress"
    assert decision.work_item.attempt_number == 1
    assert decision.work_item.publication_retry == work_item.publication_retry


def test_retry_queues_fresh_attempt_and_clears_current_execution_state() -> None:
    service = RecoveryDecisionService()
    work_item = build_work_item(status="blocked").model_copy(
        update={
            "execution_failure": WorkItemExecutionFailure(
                stage="validation",
                summary="Validation failed.",
                retry_count=1,
                run_id="run-1",
                occurred_at=datetime(2026, 8, 7, 8, 0, tzinfo=UTC),
            )
        }
    )
    request = RecoveryRequest(
        action="retry",
        actor="operator",
        request_reference="comment-42",
        expected_state_fingerprint=service.state_fingerprint(work_item),
        occurred_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
    )

    decision = service.decide(work_item=work_item, request=request, policy_eligible=True)

    assert decision.accepted is True
    assert decision.plan == "start_fresh"
    assert decision.work_item.status == "approved"
    assert decision.work_item.attempt_number == 2
    assert decision.work_item.execution_failure is None
    assert decision.work_item.recovery_events[0].prior_execution_failure is not None


def test_retry_rejects_when_current_policy_does_not_allow_fresh_attempt() -> None:
    service, request = build_request()
    work_item = build_work_item(status="blocked")

    decision = service.decide(work_item=work_item, request=request, policy_eligible=False)

    assert decision.accepted is False
    assert decision.work_item is work_item
    assert "policy" in decision.message


def test_recovery_rejects_invalid_kind_stale_or_non_blocked_work_items() -> None:
    service, request = build_request()

    invalid_kind = service.decide(
        work_item=build_work_item(status="blocked").model_copy(update={"kind": "other"}),
        request=request,
        policy_eligible=True,
    )
    stale = service.decide(
        work_item=build_work_item(status="blocked"),
        request=replace(request, expected_state_fingerprint="stale"),
        policy_eligible=True,
    )
    non_blocked = service.decide(
        work_item=build_work_item(status="approved"),
        request=request,
        policy_eligible=True,
    )

    assert invalid_kind.accepted is False
    assert "remediation" in invalid_kind.message
    assert stale.accepted is False
    assert "stale" in stale.message
    assert non_blocked.accepted is False
    assert "blocked" in non_blocked.message


def test_recovery_rejects_unsupported_action_before_selecting_a_plan() -> None:
    service = RecoveryDecisionService()
    work_item = build_work_item(status="blocked")
    request = RecoveryRequest(
        action="reopen",  # type: ignore[arg-type]
        actor="operator",
        request_reference="comment-42",
        expected_state_fingerprint=service.state_fingerprint(work_item),
        occurred_at=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
    )

    decision = service.decide(work_item=work_item, request=request, policy_eligible=True)

    assert decision.accepted is False
    assert decision.work_item is work_item
    assert decision.plan is None
    assert decision.message == "Unsupported remediation recovery action."


def test_recovery_history_retains_the_latest_ten_events() -> None:
    service = RecoveryDecisionService()
    work_item = build_work_item(status="blocked")
    for index in range(11):
        request = RecoveryRequest(
            action="dismiss",
            actor="operator",
            request_reference=f"comment-{index}",
            expected_state_fingerprint=service.state_fingerprint(work_item),
            occurred_at=datetime(2026, 8, 7, 9, index, tzinfo=UTC),
        )
        decision = service.decide(work_item=work_item, request=request, policy_eligible=True)
        work_item = decision.work_item.model_copy(update={"status": "blocked"})

    assert len(work_item.recovery_events) == 10
    assert work_item.recovery_events[0].request_reference == "comment-1"
