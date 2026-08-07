from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.policy import (
    PolicyIssueClassStateEntry,
    PolicySeverityStateEntry,
    PolicyState,
)
from zeroone_ops.models.work_item import WorkItemSourceRef, WorkItemState
from zeroone_ops.services.intake.finding_workflow_policy_service import (
    FindingWorkflowPolicyService,
)


def build_finding(*, source_id: str) -> NormalizedFinding:
    return NormalizedFinding(
        finding_id=f"{source_id}-1",
        source_id=source_id,
        severity="medium",
        title="Prefer direct truthiness",
        summary="Replace boolean equality with direct truthiness.",
        repository_path="src/service.py",
    )


def test_decide_returns_shared_default_queue_candidate_for_sonarqube() -> None:
    decision = FindingWorkflowPolicyService().decide(finding=build_finding(source_id="sonarqube"))

    assert decision.disposition == "queue_candidate"
    assert decision.reason == "default_queue_candidate"


def test_decide_returns_same_default_queue_candidate_for_other_sources() -> None:
    decision = FindingWorkflowPolicyService().decide(finding=build_finding(source_id="ruff-sarif"))

    assert decision.disposition == "queue_candidate"
    assert decision.reason == "default_queue_candidate"


def test_decide_promotion_keeps_excluded_issue_class_backlog_only() -> None:
    finding = build_finding(source_id="ruff-sarif").model_copy(
        update={
            "remediation_context": RemediationContext(diagnostic_code="E712"),
        }
    )
    policy_state = PolicyState(
        severity_policy=[
            PolicySeverityStateEntry(severity="medium", enabled=True),
        ],
        issue_class_exclusions=[
            PolicyIssueClassStateEntry(
                source="ruff-sarif",
                issue_key="E712",
                reason="Not actionable in this repository.",
            )
        ],
    )

    decision = FindingWorkflowPolicyService().decide_promotion(
        finding=finding,
        policy_state=policy_state,
    )

    assert decision.disposition == "backlog_only"
    assert decision.reason == "issue_class_excluded"


def test_is_work_item_eligible_applies_severity_and_issue_class_policy() -> None:
    """Recovery uses the same promotion policy as finding synchronization."""
    work_item = WorkItemState(
        work_item_id="work-1",
        kind="remediation",
        status="blocked",
        source=WorkItemSourceRef(
            source="ruff-sarif",
            source_item_key="src/service.py::lint_fix::E712",
            repository_scope="octo-org/octo-repo",
        ),
        summary="Prefer direct truthiness.",
        severity="medium",
        remediation_context=RemediationContext(diagnostic_code="E712"),
    )
    policy_state = PolicyState(
        severity_policy=[PolicySeverityStateEntry(severity="medium", enabled=True)],
        issue_class_exclusions=[],
    )

    assert FindingWorkflowPolicyService().is_work_item_eligible(
        work_item=work_item,
        policy_state=policy_state,
    )

    excluded_policy = policy_state.model_copy(
        update={
            "issue_class_exclusions": [
                PolicyIssueClassStateEntry(
                    source="ruff-sarif",
                    issue_key="E712",
                    reason="Excluded by operator.",
                )
            ]
        }
    )

    assert not FindingWorkflowPolicyService().is_work_item_eligible(
        work_item=work_item,
        policy_state=excluded_policy,
    )
