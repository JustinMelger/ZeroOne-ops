from pathlib import Path

from ai_sonar_bot.settings import (
    load_config,
    load_gitlab_connection_config,
    load_sonarqube_connection_config,
)


def test_settings_load_environment_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SONARQUBE_URL", raising=False)
    monkeypatch.delenv("SONARQUBE_TOKEN", raising=False)
    monkeypatch.delenv("SONARQUBE_PROJECT_KEY", raising=False)

    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "SONARQUBE_URL=https://sonarqube.example.com",
                "SONARQUBE_TOKEN=test-token",
                "SONARQUBE_PROJECT_KEY=test-project",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "base_branch": "main",
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()
    sonar = load_sonarqube_connection_config()

    assert config.base_branch == "main"
    assert config.execution_mode == "ci"
    assert sonar.url == "https://sonarqube.example.com"
    assert sonar.token == "test-token"
    assert sonar.project_key == "test-project"


def test_settings_allow_execution_mode_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_EXECUTION_MODE", "local")

    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "execution_mode": "ci",
          "base_branch": "main",
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.execution_mode == "local"
    assert config.requires_local_approval() is True


def test_gitlab_settings_fall_back_to_ci_project_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITLAB_PROJECT_ID", raising=False)
    monkeypatch.setenv("CI_PROJECT_ID", "456")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")

    config = load_gitlab_connection_config()

    assert config.project_id == "456"


def test_settings_allow_solution_artifact_ci_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AI_SONAR_BOT_WRITE_SOLUTION_ARTIFACTS_IN_CI", "true")

    (tmp_path / ".ai-sonar-bot.json").write_text(
        """
        {
          "execution_mode": "ci",
          "write_solution_artifacts_in_ci": false,
          "base_branch": "main",
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.write_solution_artifacts_in_ci is True
