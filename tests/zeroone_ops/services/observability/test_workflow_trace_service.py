"""Tests for workflow-level MLflow trace correlation."""

from contextlib import contextmanager

from zeroone_ops.models.config import MLflowTracingConfig
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.observability import workflow_trace_service
from zeroone_ops.services.observability.workflow_trace_service import (
    WorkflowTraceContext,
    WorkflowTraceService,
)
from zeroone_ops.services.shared.run_summary_builder import RunSummary


def test_workflow_trace_records_initial_and_final_tags(monkeypatch, tmp_path) -> None:
    """One trace carries stable run correlation and compact final outcome metadata."""
    tag_updates: list[dict[str, str]] = []
    monkeypatch.setattr(
        workflow_trace_service,
        "configure_mlflow_tracing",
        lambda config: config.enabled,
    )

    @contextmanager
    def fake_span(**kwargs: object):
        assert kwargs["name"] == "zeroone_ops.remediation"
        assert kwargs["attributes"] == {
            "zeroone.workflow": "remediation",
            "zeroone.run_id": "run-1",
            "zeroone.platform": "github",
            "zeroone.repository": "octo-org/octo-repo",
            "zeroone.execution_mode": "ci",
            "zeroone.dry_run": "false",
            "zeroone.model": "gpt-test",
            "zeroone.workflow_url": "https://github.example.com/run/1",
        }
        yield object()

    monkeypatch.setattr(workflow_trace_service.mlflow, "start_span", fake_span)
    monkeypatch.setattr(
        workflow_trace_service.mlflow,
        "update_current_trace",
        lambda *, tags: tag_updates.append(tags),
    )

    service = WorkflowTraceService(MLflowTracingConfig(enabled=True))
    with service.trace(
        WorkflowTraceContext(
            workflow="remediation",
            run_id="run-1",
            platform="github",
            repository="octo-org/octo-repo",
            execution_mode="ci",
            model="gpt-test",
            workflow_url="https://github.example.com/run/1",
        )
    ) as trace:
        trace.complete(
            summary=RunSummary(
                run_id="run-1",
                status=RunStatus.CHANGE_REQUEST_CREATED,
                message="published",
                state_path=tmp_path / "state.json",
                work_item_id="work-1",
                change_request_url="https://github.example.com/pull/1",
                validation_outcome="baseline_preserved",
            )
        )

    assert tag_updates == [
        {
            "zeroone.workflow": "remediation",
            "zeroone.run_id": "run-1",
            "zeroone.platform": "github",
            "zeroone.repository": "octo-org/octo-repo",
            "zeroone.execution_mode": "ci",
            "zeroone.dry_run": "false",
            "zeroone.model": "gpt-test",
            "zeroone.workflow_url": "https://github.example.com/run/1",
        },
        {
            "zeroone.outcome": "change_request_created",
            "zeroone.work_item_id": "work-1",
            "zeroone.change_request_url": "https://github.example.com/pull/1",
            "zeroone.validation_outcome": "baseline_preserved",
        },
    ]


def test_disabled_workflow_trace_does_not_start_mlflow(monkeypatch) -> None:
    """Disabled tracing remains a no-op."""
    monkeypatch.setattr(
        workflow_trace_service,
        "configure_mlflow_tracing",
        lambda config: config.enabled,
    )
    monkeypatch.setattr(
        workflow_trace_service.mlflow,
        "start_span",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("MLflow must remain disabled")),
    )

    with WorkflowTraceService(MLflowTracingConfig(enabled=False)).trace(
        WorkflowTraceContext(
            workflow="review",
            run_id="run-1",
            platform="gitlab",
            repository="group/project",
            execution_mode="ci",
        )
    ) as trace:
        assert trace.enabled is False
