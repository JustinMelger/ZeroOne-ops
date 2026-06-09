from pathlib import Path

from zeroone_ops.settings import (
    load_config,
    load_gitlab_connection_config,
    load_gitlab_project_id_override,
    load_sonarqube_connection_config,
    load_sonarqube_project_key_override,
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
    (tmp_path / ".zeroone-ops.json").write_text(
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
    monkeypatch.setenv("ZEROONE_OPS_EXECUTION_MODE", "local")

    (tmp_path / ".zeroone-ops.json").write_text(
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
    monkeypatch.setenv("ZEROONE_OPS_WRITE_SOLUTION_ARTIFACTS_IN_CI", "true")

    (tmp_path / ".zeroone-ops.json").write_text(
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


def test_settings_load_helper_following_review_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "review": {
            "enable_helper_following": false,
            "log_helper_following": true,
            "helper_follow_depth": 1,
            "max_followed_helpers_per_function": 2,
            "max_followed_helper_lines": 80,
            "max_followed_helper_lines_per_review": 160
          },
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.review.enable_helper_following is False
    assert config.review.log_helper_following is True
    assert config.review.helper_follow_depth == 1
    assert config.review.max_followed_helpers_per_function == 2
    assert config.review.max_followed_helper_lines == 80
    assert config.review.max_followed_helper_lines_per_review == 160
    assert config.review.inline_comments_enabled is False


def test_settings_load_inline_comments_review_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "review": {
            "inline_comments_enabled": true
          },
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.review.inline_comments_enabled is True


def test_settings_load_nested_remediation_and_sonarqube_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "bootstrap_severities": ["LOW", "MEDIUM"],
            "max_retry_count": 2,
            "analysis": {
              "context_lines_before": 12,
              "context_lines_after": 18,
              "max_file_bytes": 1234
            }
          },
          "sonarqube": {
            "mock_issues_path": "fixtures/sonar/issues.json"
          },
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.remediation.bootstrap_severities == ["LOW", "MEDIUM"]
    assert config.remediation.max_retry_count == 2
    assert config.remediation.analysis.context_lines_before == 12
    assert config.remediation.analysis.context_lines_after == 18
    assert config.remediation.analysis.max_file_bytes == 1234
    assert config.sonarqube.mock_issues_path == Path("fixtures/sonar/issues.json")


def test_settings_keep_legacy_flat_remediation_and_sonar_keys_compatible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "supported_severities": ["LOW"],
          "max_retry_count": 3,
          "analysis": {
            "context_lines_before": 2,
            "context_lines_after": 3,
            "max_file_bytes": 999
          },
          "mock_sonar_issues_path": "fixtures/sonar/issues.json",
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.remediation.bootstrap_severities == ["LOW"]
    assert config.remediation.max_retry_count == 3
    assert config.remediation.analysis.context_lines_before == 2
    assert config.remediation.analysis.context_lines_after == 3
    assert config.remediation.analysis.max_file_bytes == 999
    assert config.sonarqube.mock_issues_path == Path("fixtures/sonar/issues.json")


def test_settings_keep_legacy_nested_supported_severities_compatible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "supported_severities": ["LOW"]
          },
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.remediation.bootstrap_severities == ["LOW"]


def test_settings_load_runner_state_metadata_overrides(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("SONARQUBE_PROJECT_KEY", "project-key")

    assert load_gitlab_project_id_override() == "123"
    assert load_sonarqube_project_key_override() == "project-key"


def test_settings_load_default_zeroone_ops_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ZEROONE_OPS_CONFIG", raising=False)
    monkeypatch.delenv("ZEROONE_OPS_EXECUTION_MODE", raising=False)
    monkeypatch.setenv("ZEROONE_OPS_EXECUTION_MODE", "local")

    (tmp_path / ".zeroone-ops.json").write_text(
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
    assert config.base_branch == "main"


def test_settings_use_explicit_zeroone_ops_config_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / "custom.zeroone-ops.json"))

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "default",
          "gitlab": {
            "target_branch": "default",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    (tmp_path / "custom.zeroone-ops.json").write_text(
        """
        {
          "base_branch": "custom",
          "gitlab": {
            "target_branch": "custom",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.base_branch == "custom"
