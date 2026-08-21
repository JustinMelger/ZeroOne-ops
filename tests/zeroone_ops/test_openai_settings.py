from pathlib import Path

from zeroone_ops.settings import load_mlflow_tracing_config, load_openai_connection_config


def test_load_openai_connection_config_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("ZEROONE_OPS_OPENAI_SOLUTION_OUTPUT_PATH", raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-openai-key",
                "OPENAI_MODEL=gpt-4.1-mini",
                "",
            ]
        ),
        encoding="utf-8",
    )

    config = load_openai_connection_config()

    assert config.api_key == "test-openai-key"
    assert config.model == "gpt-4.1-mini"
    assert config.mlflow_enabled is False
    assert config.mlflow_tracking_uri is None
    assert config.mlflow_experiment_name is None
    assert config.mlflow_experiment_id is None


def test_load_openai_connection_config_with_mlflow_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("ZEROONE_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_NAME", "zeroone-ops-review")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_ID", "123")

    config = load_openai_connection_config()

    assert config.mlflow_enabled is True
    assert config.mlflow_tracking_uri == "http://localhost:5000"
    assert config.mlflow_experiment_name == "zeroone-ops-review"
    assert config.mlflow_experiment_id == "123"


def test_load_mlflow_tracing_config_does_not_require_openai_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Workflow tracing can start before a workflow constructs an OpenAI client."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("ZEROONE_MLFLOW_ENABLED", "true")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow.example.com")

    config = load_mlflow_tracing_config()

    assert config.enabled is True
    assert config.tracking_uri == "http://mlflow.example.com"
