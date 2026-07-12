from zeroone_ops.models.remediation import RemediationWorkItem
from zeroone_ops.services.control_plane.remediation_work_item_promotion_service import (
    RemediationWorkItemPromotionContext,
    RemediationWorkItemPromotionService,
)


def build_work_item() -> RemediationWorkItem:
    return RemediationWorkItem(
        dashboard_item_id="item-1",
        source_type="sonarqube",
        source_ref="AX-1",
        title="Fix duplicated branch logic",
        status="open",
        message="Duplicated branch logic should be simplified.",
        file_path="src/example.py",
        severity="medium",
    )


def test_decide_returns_backlog_only_when_no_promotion_trigger_is_set() -> None:
    decision = RemediationWorkItemPromotionService().decide(
        work_item=build_work_item(),
        context=RemediationWorkItemPromotionContext(),
    )

    assert decision.disposition == "backlog_only"
    assert decision.reason == "default_backlog_only"


def test_decide_promotes_selected_for_remediation_candidates() -> None:
    decision = RemediationWorkItemPromotionService().decide(
        work_item=build_work_item(),
        context=RemediationWorkItemPromotionContext(selected_for_remediation=True),
    )

    assert decision.disposition == "promote"
    assert decision.reason == "selected_for_remediation"


def test_decide_promotes_blocked_candidates_that_need_attention() -> None:
    decision = RemediationWorkItemPromotionService().decide(
        work_item=build_work_item(),
        context=RemediationWorkItemPromotionContext(blocked_requires_attention=True),
    )

    assert decision.disposition == "promote"
    assert decision.reason == "blocked_requires_attention"


def test_decide_promotes_candidates_with_open_linked_change_requests() -> None:
    decision = RemediationWorkItemPromotionService().decide(
        work_item=build_work_item(),
        context=RemediationWorkItemPromotionContext(linked_change_request_open=True),
    )

    assert decision.disposition == "promote"
    assert decision.reason == "linked_change_request_open"


def test_decide_uses_stable_trigger_precedence() -> None:
    decision = RemediationWorkItemPromotionService().decide(
        work_item=build_work_item(),
        context=RemediationWorkItemPromotionContext(
            selected_for_remediation=True,
            blocked_requires_attention=True,
            linked_change_request_open=True,
        ),
    )

    assert decision.disposition == "promote"
    assert decision.reason == "selected_for_remediation"
