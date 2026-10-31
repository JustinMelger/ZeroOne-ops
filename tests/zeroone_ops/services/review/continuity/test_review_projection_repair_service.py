"""Protect repair guards, failure boundaries, and persistence sequencing."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    PublishableReviewArtifact,
)
from zeroone_ops.models.state import ChangeRequestReviewState
from zeroone_ops.services.review.context.review_context_builder import ReviewContextBuilder
from zeroone_ops.services.review.continuity.review_projection_repair_service import (
    ReviewProjectionRepairService,
)


@pytest.mark.parametrize(
    "mode",
    [
        "success",
        "warning",
        "projection_error",
        "factory_error",
        "context_error",
        "missing_context",
        "missing_note",
        "missing_artifact",
        "invalid_classification",
        "dry_run",
        "not_pending",
        "no_state",
        "no_service",
        "historical_no_findings",
        "persistence_error",
    ],
)
def test_repair_preserves_guards_exceptions_and_write_order(tmp_path, monkeypatch, caplog, mode):
    config = AppConfig.model_validate(
        {"base_branch": "main", "gitlab": {}, "remediation": {"target_branch": "main"}}
    )
    change = ChangeRequestReviewCandidate(
        change_request_number=9,
        title="Review",
        source_branch="fix",
        target_branch="main",
        head_sha="head",
        web_url="https://example/pr/9",
    )
    context = ChangeRequestReviewContext.model_validate(change.model_dump())
    artifact = PublishableReviewArtifact(classification="no_findings", summary="Stored review")
    state = ChangeRequestReviewState(
        change_request_number=9,
        head_sha="head",
        status="no_findings",
        last_run_id="old",
        note_id=12,
        projection_retry_pending=True,
        projection_artifact=artifact,
    )
    state_service = Mock()
    service = Mock()
    service.project_review.return_value = SimpleNamespace(action="updated", warning=None)
    factory = Mock(return_value=service)
    build = Mock(return_value=SimpleNamespace(context=context, message="No source context"))
    monkeypatch.setattr(ReviewContextBuilder, "build", build)
    calls = Mock()
    calls.attach_mock(build, "context")
    calls.attach_mock(factory, "factory")
    calls.attach_mock(service.project_review, "project")
    calls.attach_mock(state_service.update_projection_retry_state, "persist")
    if mode == "warning":
        service.project_review.return_value.warning = "Head changed"
    if mode == "projection_error":
        service.project_review.side_effect = RuntimeError("Projection unavailable")
    if mode == "factory_error":
        factory.side_effect = RuntimeError("Factory unavailable")
    if mode == "context_error":
        build.side_effect = RuntimeError("Context unavailable")
    if mode == "missing_context":
        build.return_value.context = None
    if mode == "missing_note":
        state.note_id = None
    if mode == "missing_artifact":
        state.status = "findings_present"
        state.projection_artifact = None
    if mode == "invalid_classification":
        state = state.model_copy(update={"status": "failed"})
    if mode == "not_pending":
        state.projection_retry_pending = False
    if mode == "no_service":
        factory.return_value = None
    if mode == "historical_no_findings":
        state.projection_artifact = None
    if mode == "persistence_error":
        state_service.update_projection_retry_state.side_effect = RuntimeError("Save unavailable")
    repair = ReviewProjectionRepairService(
        repo_root=tmp_path,
        config=config,
        review_state_service=state_service,
        review_projection_factory=factory,
        logger=logging.getLogger("review-test"),
    )
    assert not calls.mock_calls
    before = state.model_dump_json()

    def invoke():
        return repair.retry_if_needed(
            run_id="run",
            repository_id="org/repo",
            change_request=change,
            review_state=None if mode == "no_state" else state,
            active_dry_run=mode == "dry_run",
        )

    if mode in {"factory_error", "context_error", "persistence_error"}:
        with pytest.raises(RuntimeError, match="unavailable"):
            invoke()
        if mode != "persistence_error":
            state_service.update_projection_retry_state.assert_not_called()
        return
    result = invoke()
    assert state.model_dump_json() == before
    if mode in {"dry_run", "not_pending", "no_state"}:
        assert result is None
        assert not calls.mock_calls
        return
    warning = mode not in {"success", "no_service", "historical_no_findings"}
    assert result.startswith("Review projection warning:" if warning else "Repaired pending")
    state_service.update_projection_retry_state.assert_called_once_with(
        change_request_number=9,
        head_sha="head",
        last_run_id="run",
        pending=warning,
        warning=result if warning else None,
    )
    assert calls.mock_calls[-1][0] == "persist"
    if mode in {"missing_note", "missing_artifact", "invalid_classification"}:
        build.assert_not_called()
        factory.assert_not_called()
    elif mode == "missing_context":
        factory.assert_not_called()
    elif mode == "no_service":
        service.project_review.assert_not_called()
    else:
        assert [call[0] for call in calls.mock_calls] == [
            "context",
            "factory",
            "project",
            "persist",
        ]
        assert service.project_review.call_args.kwargs["review_note_id"] == 12
        assert service.project_review.call_args.kwargs["reviewed_sha"] == "head"
        if mode == "historical_no_findings":
            assert (
                service.project_review.call_args.kwargs["artifact"].classification == "no_findings"
            )
        else:
            assert service.project_review.call_args.kwargs["artifact"] is artifact
    if mode == "projection_error":
        assert any(
            record.message == "review same-sha projection repair failed"
            for record in caplog.records
        )
