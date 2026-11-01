"""Protect retry boundaries without moving authoritative state decisions."""

import logging
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from zeroone_ops.models.analysis import SemanticSafetyAssessment
from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import RunRecord, RunStatus
from zeroone_ops.models.work_item import PublicationRetryState, WorkItemSourceRef, WorkItemState
from zeroone_ops.services.remediation.publication_request_builder import (
    RemediationPublicationRequestBuilder,
)
from zeroone_ops.services.remediation.recovery.publication_retry_service import (
    PublicationRetryResult,
)
from zeroone_ops.services.remediation.recovery.recorded_publication_retry_coordinator import (
    RecordedPublicationRetryCoordinator,
)
from zeroone_ops.services.shared.projection_payload import ProjectionSizeExceeded


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "reused",
        "dry_run",
        "missing",
        "failed",
        "empty_failure",
        "factory_error",
        "lookup_error",
        "payload",
        "build_error",
        "projection_error",
        "link_error",
        "save_error",
    ],
)
def test_recorded_retry_retains_failure_and_projection_order(tmp_path, monkeypatch, caplog, mode):
    config = AppConfig.model_validate(
        {"base_branch": "main", "gitlab": {}, "remediation": {"target_branch": "main"}}
    )
    assessment = SemanticSafetyAssessment(
        current_behavior="Current",
        intended_behavior="Intended",
        preservation_evidence=["Preserved"],
    )
    retry = PublicationRetryState(
        branch_name="remediation",
        commit_sha="sha",
        reason="change_request_publish_failed",
        semantic_safety=assessment,
    )
    state = WorkItemState(
        work_item_id="work",
        kind="remediation",
        status="in_progress",
        summary="Fix",
        file_path="src/app.py",
        source=WorkItemSourceRef(
            source="ruff", source_item_key="finding", repository_scope="org/repo"
        ),
        publication_retry=None if mode == "missing" else retry,
    )
    target = RemediationExecutionTarget(
        item_id="work",
        source_type="ruff",
        source_ref="finding",
        title="Fix",
        status="in_progress",
        message="Fix",
        file_path="src/app.py",
    )
    run_state = Mock()
    control_plane = Mock()
    retry_service = Mock()
    retry_service.retry.return_value = PublicationRetryResult(
        change_request=ChangeRequestInfo(iid=4, web_url="https://example/pr/4", title="Fix"),
        action="reused" if mode == "reused" else "created",
    )
    factory = Mock(return_value=retry_service)
    build = Mock(return_value=object())
    monkeypatch.setattr(RemediationPublicationRequestBuilder, "build", build)
    calls = Mock()
    for name, dependency in [
        ("factory", factory),
        ("build", build),
        ("retry", retry_service.retry),
        ("blocked", control_plane.mark_publish_blocked),
        ("link", control_plane.sync_change_request_link),
        ("finish", run_state.finish_work_item),
    ]:
        calls.attach_mock(dependency, name)
    if mode in {"failed", "empty_failure", "projection_error"}:
        retry_service.retry.return_value = PublicationRetryResult(
            error_message=None if mode == "empty_failure" else "Publish failed"
        )
    errors = {
        "factory_error": factory,
        "lookup_error": retry_service.retry,
        "build_error": build,
        "link_error": control_plane.sync_change_request_link,
        "save_error": run_state.finish_work_item,
        "projection_error": control_plane.mark_publish_blocked,
    }
    if mode in errors:
        errors[mode].side_effect = RuntimeError("Unavailable")
    if mode == "payload":
        build.side_effect = ProjectionSizeExceeded("Oversized")
    coordinator = RecordedPublicationRetryCoordinator(
        config=config,
        run_state_service=run_state,
        remediation_control_plane=control_plane,
        retry_service_factory=factory,
        logger=logging.getLogger("retry-test"),
    )
    assert not calls.mock_calls
    before = state.model_dump_json(), target.model_dump_json()
    options = dict(
        selected_target=target,
        claimed_work_item=state,
        record=RunRecord(
            run_id="run",
            status=RunStatus.STARTED,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        active_dry_run=mode == "dry_run",
    )
    if mode == "missing":
        with pytest.raises(ValueError, match="recorded retry state"):
            coordinator.run(**options)
        assert not calls.mock_calls
        return
    if mode in {"factory_error", "lookup_error", "build_error", "link_error", "save_error"}:
        with pytest.raises(RuntimeError, match="Unavailable"):
            coordinator.run(**options)
        control_plane.mark_publish_blocked.assert_not_called()
        return
    assert coordinator.run(**options) is run_state.finish_work_item.return_value
    assert before == (state.model_dump_json(), target.model_dump_json())
    names = [call[0] for call in calls.mock_calls]
    if mode == "dry_run":
        assert names == ["finish"]
        assert run_state.finish_work_item.call_args.kwargs["status"] == RunStatus.SELECTED
        return
    if mode in {"failed", "empty_failure", "projection_error", "payload"}:
        assert names == (
            ["factory", "build", "blocked", "finish"]
            if mode == "payload"
            else ["factory", "build", "retry", "blocked", "finish"]
        )
        assert control_plane.mark_publish_blocked.call_args.kwargs["publication_retry"] is retry
        assert run_state.finish_work_item.call_args.kwargs["status"] == RunStatus.FAILED
    else:
        assert names == ["factory", "build", "retry", "link", "finish"]
        assert (
            control_plane.sync_change_request_link.call_args.kwargs["semantic_safety"].assessment
            == assessment
        )
        assert (
            run_state.finish_work_item.call_args.kwargs["change_request_action"]
            == retry_service.retry.return_value.action
        )
    if mode == "projection_error":
        assert len(caplog.records) == 1
        assert caplog.records[0].getMessage() == "work-item publication retry projection failed"
        assert caplog.records[0].exc_info is not None
