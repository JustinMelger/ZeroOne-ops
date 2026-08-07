from zeroone_ops.models.dashboard import DashboardItem
from zeroone_ops.models.work_item import PublicationRetryState
from zeroone_ops.services.dashboard.dashboard_recovery_state import (
    apply_work_item_recovery_state,
    dashboard_item_to_work_item_state,
)


def build_item(*, status: str = "failed") -> DashboardItem:
    return DashboardItem(
        id="sonar:AX-123",
        source="sonarqube",
        type="static_analysis_fix",
        status=status,
        title="Use direct truthiness.",
        summary="Avoid comparing a condition with True.",
        priority="medium",
        source_reference="AX-123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        project="sample-project",
        automation_severity="medium",
        branch_name="zeroone-ops/sonarqube/ax-123/service",
        commit_sha="abc123",
        change_request_number=17,
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        attempt_number=1,
    )


def test_dashboard_item_maps_to_shared_blocked_recovery_state() -> None:
    work_item = dashboard_item_to_work_item_state(build_item())

    assert work_item.status == "blocked"
    assert work_item.source.source == "sonarqube"
    assert work_item.source.source_item_key == "AX-123"
    assert work_item.linked_change_request is not None
    assert work_item.linked_change_request.number == 17
    assert work_item.remediation_context.diagnostic_code == "python:S1125"


def test_apply_fresh_recovery_clears_prior_change_request_traceability() -> None:
    item = build_item()
    work_item = dashboard_item_to_work_item_state(item).model_copy(
        update={
            "status": "approved",
            "attempt_number": 2,
            "linked_change_request": None,
            "publication_retry": None,
        }
    )

    updated = apply_work_item_recovery_state(item=item, work_item=work_item)

    assert updated.status == "open"
    assert updated.attempt_number == 2
    assert updated.retry_count == 1
    assert updated.branch_name is None
    assert updated.commit_sha is None
    assert updated.change_request_number is None
    assert updated.change_request_url is None


def test_apply_publication_retry_preserves_recorded_branch_traceability() -> None:
    item = build_item()
    retry = PublicationRetryState(
        branch_name="zeroone-ops/sonarqube/ax-123/service",
        commit_sha="abc123",
        reason="change_request_publish_failed",
    )
    work_item = dashboard_item_to_work_item_state(item).model_copy(
        update={
            "status": "approved",
            "linked_change_request": None,
            "publication_retry": retry,
        }
    )

    updated = apply_work_item_recovery_state(item=item, work_item=work_item)

    assert updated.status == "open"
    assert updated.publication_retry == retry
    assert updated.branch_name == retry.branch_name
    assert updated.commit_sha == retry.commit_sha
    assert updated.change_request_number is None
    assert updated.change_request_url is None
