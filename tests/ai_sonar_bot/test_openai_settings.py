from pathlib import Path

from ai_sonar_bot.settings import load_openai_connection_config


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
