"""Protect repair guards, failure boundaries, and persistence sequencing."""

import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    PublishableReviewArtifact,
)
from zeroone_ops.models.review_overview import ReviewOverviewPass
from zeroone_ops.models.state import ChangeRequestReviewState
from zeroone_ops.providers.review.platform import ReviewPlatformClientError
from zeroone_ops.services.review.context.review_context_builder import ReviewContextBuilder
from zeroone_ops.services.review.continuity.review_projection_repair_service import (
    ReviewProjectionRepairService,
)
from zeroone_ops.services.review.publish.review_overview_codec import ReviewOverviewError


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


@pytest.mark.parametrize("projection_warning", [None, "Provider projection failed"])
@pytest.mark.parametrize(
    "metadata_error",
    [None, OSError, ReviewOverviewError, ReviewPlatformClientError, httpx.HTTPError, RuntimeError],
)
@pytest.mark.parametrize("complete", [False, True])
def test_overview_repair_uses_logical_reference_and_synchronizes_metadata(
    tmp_path, monkeypatch, projection_warning, metadata_error, complete
):
    change = ChangeRequestReviewCandidate(
        change_request_number=9,
        title="Review",
        source_branch="fix",
        target_branch="main",
        head_sha="head",
        web_url="https://example/pr/9",
    )
    artifact = PublishableReviewArtifact(classification="no_findings", summary="Stored review")
    state = ChangeRequestReviewState(
        change_request_number=9,
        head_sha="head",
        status="no_findings",
        last_run_id="old",
        review_pass_id="logical-pass",
        projection_reference="logical-reference",
        projection_retry_pending=True,
        projection_artifact=artifact,
    )
    if complete:
        state.overview_pass = ReviewOverviewPass(
            pass_id="logical-pass",
            run_id="original-run",
            head_sha="head",
            sequence=3,
            completed_at=datetime(2026, 1, 1, tzinfo=UTC),
            artifact=artifact,
            projection_reference="logical-reference",
        ).model_copy(deep=True)
    projection = Mock()
    projection.project_review.return_value = SimpleNamespace(
        action="updated", warning=projection_warning
    )
    coordinator = Mock()
    if metadata_error:
        coordinator.write_metadata.side_effect = metadata_error("Metadata unavailable")
    state_service = Mock()
    monkeypatch.setattr(
        ReviewContextBuilder,
        "build",
        Mock(
            return_value=SimpleNamespace(
                context=ChangeRequestReviewContext.model_validate(change.model_dump())
            )
        ),
    )
    repair = ReviewProjectionRepairService(
        repo_root=tmp_path,
        config=AppConfig.model_validate(
            {"base_branch": "main", "gitlab": {}, "remediation": {"target_branch": "main"}}
        ),
        review_state_service=state_service,
        review_projection_factory=lambda: projection,
        logger=logging.getLogger("review-test"),
        overview_coordinator=coordinator,
    )
    if metadata_error is RuntimeError:
        with pytest.raises(RuntimeError, match="Metadata unavailable"):
            repair.retry_if_needed(
                run_id="run",
                repository_id="org/repo",
                change_request=change,
                review_state=state,
                active_dry_run=False,
            )
        state_service.update_projection_retry_state.assert_not_called()
        return
    result = repair.retry_if_needed(
        run_id="run",
        repository_id="org/repo",
        change_request=change,
        review_state=state,
        active_dry_run=False,
    )
    assert projection.project_review.call_args.kwargs["review_pass_id"] == "logical-reference"
    assert projection.project_review.call_args.kwargs["artifact"] is artifact
    coordinator.write_metadata.assert_called_once_with(
        repository_id="org/repo",
        change_request_number=9,
        head_sha="head",
        pass_id="logical-pass",
        artifact=artifact,
        inline_decisions=[] if complete else None,
        projection_pending=projection_warning is not None,
        projection_warning=(
            f"Review projection warning: {projection_warning}" if projection_warning else None
        ),
    )
    assert coordinator.write_metadata.call_args.kwargs["artifact"] is state.projection_artifact
    persisted = state_service.update_projection_retry_state.call_args.kwargs
    assert persisted["pending"] is (metadata_error is not None or projection_warning is not None)
    if metadata_error:
        assert "Metadata unavailable" in result
    if projection_warning:
        assert projection_warning in result
    assert persisted["warning"] == (result if persisted["pending"] else None)
