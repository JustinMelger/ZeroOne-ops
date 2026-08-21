from zeroone_ops.models.dashboard import (
    DashboardPolicyState,
    DashboardSeverityPolicyStateEntry,
)
from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.intake.finding_promotion_capacity_service import (
    FindingPromotionCapacityService,
)


def _finding(
    *,
    finding_id: str,
    severity: str = "high",
    source_id: str = "ruff",
) -> NormalizedFinding:
    return NormalizedFinding(
        finding_id=finding_id,
        source_id=source_id,
        severity=severity,  # type: ignore[arg-type]
        title=f"Finding {finding_id}",
        summary=f"Summary for {finding_id}.",
        repository_path="src/service.py",
        line_start=12,
        remediation_context=RemediationContext(category="static_analysis_fix"),
    )


def _work_item(*, finding_id: str, status: str) -> WorkItemState:
    return WorkItemState(
        work_item_id=f"work-{finding_id}",
        kind="remediation",
        status=status,  # type: ignore[arg-type]
        source=WorkItemSourceRef(
            source="ruff",
            source_item_key=finding_id,
            repository_scope="octo-org/octo-repo",
        ),
        summary=f"Finding {finding_id}",
        severity="high",
    )


def _policy_state() -> DashboardPolicyState:
    return DashboardPolicyState(
        severity_policy=[
            DashboardSeverityPolicyStateEntry(severity="low", enabled=True),
            DashboardSeverityPolicyStateEntry(severity="medium", enabled=True),
            DashboardSeverityPolicyStateEntry(severity="high", enabled=True),
        ]
    )


def test_plan_uses_remaining_capacity_in_severity_order() -> None:
    high = _finding(finding_id="high", severity="high")
    medium = _finding(finding_id="medium", severity="medium")

    plan = FindingPromotionCapacityService().plan(
        findings=[medium, high],
        policy_state=_policy_state(),
        open_work_items=[_work_item(finding_id="already-active", status="approved")],
        repository_scope="octo-org/octo-repo",
        max_active_work_items=2,
    )

    assert plan.active_work_item_count == 1
    assert plan.decision_for(high).disposition == "promote"
    assert plan.decision_for(medium).reason == "promotion_capacity_exhausted"


def test_plan_stably_breaks_same_severity_ties_by_finding_identity() -> None:
    first = _finding(finding_id="a")
    second = _finding(finding_id="b")

    plan = FindingPromotionCapacityService().plan(
        findings=[second, first],
        policy_state=_policy_state(),
        open_work_items=[],
        repository_scope="octo-org/octo-repo",
        max_active_work_items=1,
    )

    assert plan.decision_for(first).disposition == "promote"
    assert plan.decision_for(second).reason == "promotion_capacity_exhausted"


def test_plan_prioritizes_configured_sources_before_severity() -> None:
    lower_priority_high = _finding(
        finding_id="high",
        severity="high",
        source_id="ruff-sarif",
    )
    higher_priority_medium = _finding(
        finding_id="medium",
        severity="medium",
        source_id="semgrep-sarif",
    )

    plan = FindingPromotionCapacityService().plan(
        findings=[lower_priority_high, higher_priority_medium],
        policy_state=_policy_state(),
        open_work_items=[],
        repository_scope="octo-org/octo-repo",
        max_active_work_items=1,
        source_priorities={"semgrep-sarif": 20, "ruff-sarif": 100},
    )

    assert plan.decision_for(higher_priority_medium).disposition == "promote"
    assert plan.decision_for(lower_priority_high).reason == "promotion_capacity_exhausted"


def test_plan_uses_severity_then_identity_when_source_priorities_are_equal() -> None:
    medium = _finding(finding_id="medium", severity="medium", source_id="mypy-sarif")
    high = _finding(finding_id="high", severity="high", source_id="ruff-sarif")

    plan = FindingPromotionCapacityService().plan(
        findings=[medium, high],
        policy_state=_policy_state(),
        open_work_items=[],
        repository_scope="octo-org/octo-repo",
        max_active_work_items=1,
        source_priorities={"mypy-sarif": 50, "ruff-sarif": 50},
    )

    assert plan.decision_for(high).disposition == "promote"
    assert plan.decision_for(medium).reason == "promotion_capacity_exhausted"


def test_plan_uses_the_default_source_priority_for_unconfigured_sources() -> None:
    high = _finding(finding_id="high", severity="high", source_id="unconfigured-sarif")
    medium = _finding(finding_id="medium", severity="medium", source_id="ruff-sarif")

    plan = FindingPromotionCapacityService().plan(
        findings=[medium, high],
        policy_state=_policy_state(),
        open_work_items=[],
        repository_scope="octo-org/octo-repo",
        max_active_work_items=1,
        source_priorities={"ruff-sarif": 100},
    )

    assert plan.decision_for(high).disposition == "promote"
    assert plan.decision_for(medium).reason == "promotion_capacity_exhausted"


def test_plan_does_not_count_protected_work_or_block_candidate_repromotion() -> None:
    candidate = _finding(finding_id="candidate")

    plan = FindingPromotionCapacityService().plan(
        findings=[candidate],
        policy_state=_policy_state(),
        open_work_items=[
            _work_item(finding_id="blocked", status="blocked"),
            _work_item(finding_id="dismissed", status="dismissed"),
            _work_item(finding_id="candidate", status="candidate"),
        ],
        repository_scope="octo-org/octo-repo",
        max_active_work_items=1,
    )

    assert plan.active_work_item_count == 0
    assert plan.decision_for(candidate).disposition == "promote"


def test_plan_preserves_active_work_when_the_cap_is_lowered() -> None:
    new_finding = _finding(finding_id="new")

    plan = FindingPromotionCapacityService().plan(
        findings=[new_finding],
        policy_state=_policy_state(),
        open_work_items=[
            _work_item(finding_id="active-one", status="approved"),
            _work_item(finding_id="active-two", status="in_progress"),
        ],
        repository_scope="octo-org/octo-repo",
        max_active_work_items=1,
    )

    assert plan.active_work_item_count == 2
    assert plan.decision_for(new_finding).reason == "promotion_capacity_exhausted"


def test_plan_counts_duplicate_active_records_against_capacity() -> None:
    new_finding = _finding(finding_id="new")
    duplicate = _work_item(finding_id="duplicate", status="approved")

    plan = FindingPromotionCapacityService().plan(
        findings=[new_finding],
        policy_state=_policy_state(),
        open_work_items=[
            duplicate,
            duplicate.model_copy(update={"work_item_id": "work-duplicate-copy"}),
        ],
        repository_scope="octo-org/octo-repo",
        max_active_work_items=2,
    )

    assert plan.active_work_item_count == 2
    assert plan.decision_for(new_finding).reason == "promotion_capacity_exhausted"
