"""Build valid persisted batch evidence for verified review linkage."""

from zeroone_ops.models.analysis import SemanticSafetyAssessment
from zeroone_ops.models.batch_execution import BatchAnalysisCoverage, BatchAttemptEvidence
from zeroone_ops.models.finding import NormalizedFinding, RemediationContext
from zeroone_ops.models.finding_batch import BatchMemberObservation, WorkItemBatch
from zeroone_ops.models.finding_batch_snapshot import BatchFindingSnapshot
from zeroone_ops.models.state import utc_now
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    WorkItemSemanticSafety,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.services.intake.finding_batch_identity import create_finding_batch_identity
from zeroone_ops.services.intake.finding_batch_ownership import finding_batch_group

from .provider_api import REPOSITORY_SCOPE
from .review_cases import REVIEW_PATH, ReviewCase


def linked_review_work_item(case: ReviewCase) -> WorkItemState:
    """Seed renderer-owned evidence, not authority reconstructed from a request description."""
    finding = NormalizedFinding(
        finding_id=f"member-{case.number}",
        source_id="mypy-sarif",
        severity="medium",
        title="Add precise type annotations",
        summary=f"Targeted annotation {case.marker}",
        repository_path=REVIEW_PATH,
        line_start=case.finding.line_start,
        remediation_context=RemediationContext(
            category="static_analysis_fix", diagnostic_code="no-untyped-def"
        ),
    )
    member = BatchFindingSnapshot.model_validate(finding.model_dump())
    batch = WorkItemBatch(
        group=finding_batch_group(repository_scope=REPOSITORY_SCOPE, finding=finding),
        members=(member,),
        observations=(
            BatchMemberObservation(
                finding_id=member.finding_id,
                last_confirmed_presence="detected",
                freshness="current",
                sync_run_id=f"sync-{case.number}",
                observed_at=utc_now(),
                last_confirmed_sync_run_id=f"sync-{case.number}",
                last_confirmed_finding=member,
            ),
        ),
    )
    identity = create_finding_batch_identity()
    return WorkItemState(
        work_item_id=identity.work_item_id,
        kind="remediation",
        status="in_progress",
        source=WorkItemSourceRef(
            source=finding.source_id,
            source_item_key=identity.source_item_key,
            repository_scope=REPOSITORY_SCOPE,
        ),
        file_path=REVIEW_PATH,
        line=finding.line_start,
        summary=finding.summary,
        severity=finding.severity,
        remediation_context=finding.remediation_context,
        linked_change_request=ChangeRequestRef(number=case.number, web_url=case.url),
        batch=batch,
        attempt_number=1,
        batch_attempt=BatchAttemptEvidence(
            batch_id=identity.work_item_id,
            attempt_number=1,
            run_id=f"execution-{case.number}",
            members=batch.members,
            observation_run_ids=(f"sync-{case.number}",),
            coverage=BatchAnalysisCoverage(addressable_ids=(member.finding_id,)),
        ),
        semantic_safety=WorkItemSemanticSafety(
            assessment=SemanticSafetyAssessment(
                current_behavior=f"The original {case.marker} behavior is available.",
                intended_behavior=f"Add annotations while preserving {case.marker} behavior.",
                preservation_evidence=[
                    f"The recorded {case.marker} claim requires independent review."
                ],
            )
        ),
    )
