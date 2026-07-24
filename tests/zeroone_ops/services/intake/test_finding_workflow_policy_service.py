from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.policy import (
    PolicyIssueClassStateEntry,
    PolicySeverityStateEntry,
    PolicyState,
)
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
