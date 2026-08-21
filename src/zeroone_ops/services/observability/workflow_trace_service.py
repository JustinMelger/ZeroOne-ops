"""Best-effort root traces for model-using ZeroOne Ops workflows."""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

import mlflow

from zeroone_ops.models.config import MLflowTracingConfig
from zeroone_ops.models.state import FailureDetails
from zeroone_ops.services.observability.mlflow_tracing import configure_mlflow_tracing
from zeroone_ops.services.shared.run_summary_builder import RunSummary

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkflowTraceContext:
    """Describe the stable operator correlation values for one workflow trace."""

    workflow: str
    run_id: str
    platform: str
    repository: str
    execution_mode: str
    model: str | None = None
    workflow_url: str | None = None
    change_request_number: int | None = None


class WorkflowTraceScope:
    """Attach final workflow outcome metadata before the root trace closes."""

    def __init__(self, *, enabled: bool, trace_id: str | None = None) -> None:
        """Initialize a scope that is either active or a no-op."""
        self.enabled = enabled
        self.trace_id = trace_id

    def complete(self, *, summary: RunSummary, failure: FailureDetails | None = None) -> None:
        """Attach compact final outcome metadata to the active workflow trace."""
        if not self.enabled:
            return
        tags = {
            "zeroone.outcome": summary.status.value,
        }
        if summary.work_item_id:
            tags["zeroone.work_item_id"] = summary.work_item_id
        if summary.change_request_url:
            tags["zeroone.change_request_url"] = summary.change_request_url
        validation_outcome = summary.validation_outcome
        if validation_outcome is None and failure is not None:
            validation_outcome = failure.validation_outcome
        if validation_outcome is not None:
            tags["zeroone.validation_outcome"] = validation_outcome
        try:
            mlflow.update_current_trace(tags=tags)
        except Exception:
            LOGGER.warning("MLflow workflow trace completion failed", exc_info=True)
            return
        LOGGER.info(
            "MLflow workflow trace completed",
            extra={"zeroone_run_id": summary.run_id, "mlflow_trace_id": self.trace_id},
        )


class WorkflowTraceService:
    """Start optional root traces without changing workflow outcomes."""

    def __init__(self, config: MLflowTracingConfig) -> None:
        """Initialize tracing from environment-derived MLflow settings."""
        self.config = config

    @contextmanager
    def trace(self, context: WorkflowTraceContext) -> Generator[WorkflowTraceScope]:
        """Yield a scope for one live model-using workflow execution."""
        if not configure_mlflow_tracing(self.config):
            yield WorkflowTraceScope(enabled=False)
            return

        tags = _initial_tags(context)
        try:
            span_context = mlflow.start_span(
                name=f"zeroone_ops.{context.workflow}",
                span_type="CHAIN",
                attributes=tags,
            )
        except Exception:
            LOGGER.warning("MLflow workflow tracing failed; continuing workflow.", exc_info=True)
            yield WorkflowTraceScope(enabled=False)
            return

        workflow_failed = False
        try:
            with span_context as span:
                try:
                    mlflow.update_current_trace(tags=tags)
                except Exception:
                    LOGGER.warning("MLflow workflow trace initialization failed", exc_info=True)
                LOGGER.info(
                    "MLflow workflow trace started",
                    extra={
                        "zeroone_run_id": context.run_id,
                        "zeroone_workflow": context.workflow,
                        "mlflow_trace_id": _trace_id(span),
                    },
                )
                try:
                    yield WorkflowTraceScope(enabled=True, trace_id=_trace_id(span))
                except BaseException:
                    workflow_failed = True
                    raise
        except Exception:
            if workflow_failed:
                raise
            LOGGER.warning("MLflow workflow tracing failed; continuing workflow.", exc_info=True)


def workflow_execution_url() -> str | None:
    """Return the provider-native CI workflow URL when the environment supplies one."""
    if gitlab_url := os.environ.get("CI_PIPELINE_URL"):
        return gitlab_url
    server_url = os.environ.get("GITHUB_SERVER_URL")
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if server_url and repository and run_id:
        return f"{server_url}/{repository}/actions/runs/{run_id}"
    return None


def workflow_model() -> str | None:
    """Return the configured model name without loading OpenAI credentials."""
    return os.environ.get("OPENAI_MODEL")


def _initial_tags(context: WorkflowTraceContext) -> dict[str, str]:
    """Build string-only trace tags for safe MLflow filtering."""
    tags = {
        "zeroone.workflow": context.workflow,
        "zeroone.run_id": context.run_id,
        "zeroone.platform": context.platform,
        "zeroone.repository": context.repository,
        "zeroone.execution_mode": context.execution_mode,
        "zeroone.dry_run": "false",
    }
    if context.model:
        tags["zeroone.model"] = context.model
    if context.workflow_url:
        tags["zeroone.workflow_url"] = context.workflow_url
    if context.change_request_number is not None:
        tags["zeroone.change_request_number"] = str(context.change_request_number)
    return tags


def _trace_id(span: object) -> str | None:
    """Return a trace identifier when the active MLflow span exposes one."""
    trace_id = getattr(span, "trace_id", None)
    return trace_id if isinstance(trace_id, str) else None
