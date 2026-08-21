"""Tests for shared MLflow tracing setup."""

import logging

from zeroone_ops.models.config import MLflowTracingConfig
from zeroone_ops.services.observability import mlflow_tracing


def test_configure_mlflow_tracing_is_idempotent(monkeypatch) -> None:
    """MLflow setup configures one destination and one OpenAI autologger."""
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(mlflow_tracing, "_MLFLOW_OPENAI_AUTOLOGGING_CONFIGURED", False)
    monkeypatch.setattr(
        mlflow_tracing.mlflow,
        "set_tracking_uri",
        lambda uri: calls.append(("tracking_uri", uri)),
    )
    monkeypatch.setattr(
        mlflow_tracing.mlflow,
        "set_experiment",
        lambda name: calls.append(("experiment", name)),
    )
    monkeypatch.setattr(
        mlflow_tracing.mlflow_tracing,
        "set_destination",
        lambda destination: calls.append(("destination", destination.experiment_id)),
    )
    monkeypatch.setattr(
        mlflow_tracing.mlflow_openai,
        "autolog",
        lambda **kwargs: calls.append(("autolog", kwargs)),
    )
    config = MLflowTracingConfig(
        enabled=True,
        tracking_uri="http://mlflow.example.com",
        experiment_name="zeroone-ops",
        experiment_id="123",
    )

    assert mlflow_tracing.configure_mlflow_tracing(config) is True
    assert mlflow_tracing.configure_mlflow_tracing(config) is True
    assert calls == [
        ("tracking_uri", "http://mlflow.example.com"),
        ("experiment", "zeroone-ops"),
        ("destination", "123"),
        ("autolog", {"silent": True, "log_traces": True}),
    ]


def test_configure_mlflow_tracing_continues_after_setup_failure(monkeypatch, caplog) -> None:
    """MLflow failures do not prevent the enclosing workflow from continuing."""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(mlflow_tracing, "_MLFLOW_OPENAI_AUTOLOGGING_CONFIGURED", False)

    def fail_autolog(**kwargs: object) -> None:
        del kwargs
        raise RuntimeError("boom")

    monkeypatch.setattr(mlflow_tracing.mlflow_openai, "autolog", fail_autolog)

    assert mlflow_tracing.configure_mlflow_tracing(MLflowTracingConfig(enabled=True)) is False
    assert "setup failed; continuing without tracing" in caplog.text.lower()
