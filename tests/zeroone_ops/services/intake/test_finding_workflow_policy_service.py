from zeroone_ops.models.finding import NormalizedFinding
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
