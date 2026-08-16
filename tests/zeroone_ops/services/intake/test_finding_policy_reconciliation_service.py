from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.intake.finding_policy_reconciliation_service import (
    FindingPolicyReconciliationService,
)


def _work_item(*, status: str = "approved", linked: bool = False) -> WorkItemState:
    return WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status=status,  # type: ignore[arg-type]
        source=WorkItemSourceRef(source="ruff", source_item_key="finding-1"),
        summary="Finding",
        linked_change_request=(
            {"number": 1, "web_url": "https://example.com/change/1"} if linked else None
        ),
    )


def test_defers_only_unlinked_candidate_or_approved_work() -> None:
    service = FindingPolicyReconciliationService()

    assert (
        service.decide_for_current_finding(
            work_item=_work_item(), policy_eligible=False, promotion_eligible=False
        ).action
        == "defer"
    )
    assert (
        service.decide_for_current_finding(
            work_item=_work_item(status="in_progress"),
            policy_eligible=False,
            promotion_eligible=False,
        ).action
        == "retain_protected"
    )
    assert (
        service.decide_for_current_finding(
            work_item=_work_item(linked=True), policy_eligible=False, promotion_eligible=False
        ).action
        == "retain_protected"
    )


def test_reopens_or_retains_deferred_work_according_to_capacity() -> None:
    service = FindingPolicyReconciliationService()

    assert (
        service.decide_for_current_finding(
            work_item=_work_item(status="policy_deferred"),
            policy_eligible=True,
            promotion_eligible=True,
        ).action
        == "reopen_approved"
    )
    assert (
        service.decide_for_current_finding(
            work_item=_work_item(status="policy_deferred"),
            policy_eligible=True,
            promotion_eligible=False,
        ).action
        == "move_to_capacity_deferred"
    )


def test_reconciles_capacity_deferred_work_between_policy_and_capacity() -> None:
    service = FindingPolicyReconciliationService()

    assert (
        service.decide_for_current_finding(
            work_item=_work_item(status="capacity_deferred"),
            policy_eligible=False,
            promotion_eligible=False,
        ).action
        == "move_to_policy_deferred"
    )
    assert (
        service.decide_for_current_finding(
            work_item=_work_item(status="capacity_deferred"),
            policy_eligible=True,
            promotion_eligible=False,
        ).action
        == "retain_capacity_deferred"
    )


def test_retains_approved_work_when_capacity_is_exhausted() -> None:
    service = FindingPolicyReconciliationService()

    assert (
        service.decide_for_current_finding(
            work_item=_work_item(status="approved"),
            policy_eligible=True,
            promotion_eligible=False,
        ).action
        == "none"
    )


def test_completes_missing_safe_work_only_for_managed_source() -> None:
    service = FindingPolicyReconciliationService()
    deferred = _work_item(status="policy_deferred")
    capacity_deferred = _work_item(status="capacity_deferred")

    assert (
        service.decide_for_missing_finding(work_item=deferred, source_is_managed=True).action
        == "complete_no_longer_detected"
    )
    assert (
        service.decide_for_missing_finding(work_item=deferred, source_is_managed=False).action
        == "none"
    )
    assert (
        service.decide_for_missing_finding(
            work_item=capacity_deferred, source_is_managed=True
        ).action
        == "complete_no_longer_detected"
    )


def test_completes_missing_unlinked_open_work_but_retains_protected_work() -> None:
    service = FindingPolicyReconciliationService()

    assert (
        service.decide_for_missing_finding(
            work_item=_work_item(status="candidate"), source_is_managed=True
        ).action
        == "complete_no_longer_detected"
    )
    assert (
        service.decide_for_missing_finding(
            work_item=_work_item(status="approved"), source_is_managed=True
        ).action
        == "complete_no_longer_detected"
    )
    for work_item in (
        _work_item(status="in_progress"),
        _work_item(status="blocked"),
        _work_item(status="dismissed"),
        _work_item(status="approved", linked=True),
    ):
        assert (
            service.decide_for_missing_finding(work_item=work_item, source_is_managed=True).action
            == "none"
        )
