"""Optional MLflow setup shared by workflow and OpenAI instrumentation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import cast

import mlflow
import mlflow.openai as mlflow_openai
import mlflow.tracing as mlflow_tracing
from mlflow.entities.trace_location import MlflowExperimentLocation

from zeroone_ops.models.config import MLflowTracingConfig

LOGGER = logging.getLogger(__name__)
_MLFLOW_OPENAI_AUTOLOGGING_CONFIGURED = False


def configure_mlflow_tracing(config: MLflowTracingConfig) -> bool:
    """Configure optional MLflow tracing and return whether it is available."""
    global _MLFLOW_OPENAI_AUTOLOGGING_CONFIGURED

    if not config.enabled:
        return False
    if _MLFLOW_OPENAI_AUTOLOGGING_CONFIGURED:
        return True

    try:
        if config.tracking_uri:
            mlflow.set_tracking_uri(config.tracking_uri)
        if config.experiment_name:
            mlflow.set_experiment(config.experiment_name)
        if config.experiment_id:
            mlflow_tracing.set_destination(
                MlflowExperimentLocation(experiment_id=config.experiment_id)
            )
        autolog = cast(Callable[..., None], mlflow_openai.autolog)
        autolog(silent=True, log_traces=True)
    except Exception:
        LOGGER.warning(
            "MLflow OpenAI autologging setup failed; continuing without tracing.",
            exc_info=True,
        )
        return False

    _MLFLOW_OPENAI_AUTOLOGGING_CONFIGURED = True
    LOGGER.info(
        "MLflow OpenAI autologging enabled",
        extra={
            "mlflow_tracking_uri": config.tracking_uri,
            "mlflow_experiment_name": config.experiment_name,
            "mlflow_experiment_id": config.experiment_id,
        },
    )
    return True
