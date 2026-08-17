from pathlib import Path

import pytest
from pytest import LogCaptureFixture

from zeroone_ops.settings import (
    SettingsError,
    load_config,
    load_current_github_issue_comment_id,
    load_current_github_issue_number,
    load_current_github_pull_request_head_sha,
    load_current_github_pull_request_number,
    load_github_connection_config,
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
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
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
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.execution_mode == "local"
    assert config.requires_local_approval() is True


def test_settings_default_gitlab_control_plane_mode_is_issues(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.require_gitlab_config(reason="test").control_plane_mode == "issues"


def test_settings_accept_gitlab_issue_control_plane_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
            "control_plane_mode": "issues",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.require_gitlab_config(reason="test").control_plane_mode == "issues"


def test_settings_accept_legacy_gitlab_dashboard_control_plane_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
            "control_plane_mode": "dashboard",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.require_gitlab_config(reason="test").control_plane_mode == "dashboard"


def test_gitlab_settings_fall_back_to_ci_project_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITLAB_PROJECT_ID", raising=False)
    monkeypatch.setenv("CI_PROJECT_ID", "456")
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")

    config = load_gitlab_connection_config()

    assert config.project_id == "456"


def test_github_settings_load_connection_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    monkeypatch.setenv("GITHUB_API_URL", "https://github.example.com/api/v3")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.example.com")

    config = load_github_connection_config()

    assert config.token == "github-token"
    assert config.repository == "octo-org/octo-repo"
    assert config.api_url == "https://github.example.com/api/v3"
    assert config.server_url == "https://github.example.com"


def test_github_settings_load_pull_request_number_from_event_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    event_path = tmp_path / "github-event.json"
    event_path.write_text('{"pull_request": {"number": 42}}', encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    assert load_current_github_pull_request_number() == 42


def test_github_settings_load_issue_number_from_event_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    event_path = tmp_path / "github-event.json"
    event_path.write_text('{"issue": {"number": 42}}', encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    assert load_current_github_issue_number() == 42


def test_github_settings_load_issue_comment_id_from_event_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    event_path = tmp_path / "github-event.json"
    event_path.write_text(
        '{"issue": {"number": 42}, "comment": {"id": 84}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    assert load_current_github_issue_comment_id() == 84


def test_github_settings_reject_non_integer_pull_request_number(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    event_path = tmp_path / "github-event.json"
    event_path.write_text('{"pull_request": {"number": "42"}}', encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    try:
        load_current_github_pull_request_number()
    except SettingsError as error:
        assert "pull_request.number must be an integer" in str(error)
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected SettingsError for non-integer pull_request.number")


def test_github_settings_load_pull_request_head_sha_from_event_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    event_path = tmp_path / "github-event.json"
    event_path.write_text(
        '{"pull_request": {"number": 42, "head": {"sha": "abc123def456"}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))

    assert load_current_github_pull_request_head_sha() == "abc123def456"


def test_settings_allow_github_review_config_without_gitlab_block(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "platform": "github"
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.platform == "github"
    assert config.gitlab is None


def test_settings_load_github_pull_request_publish_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "platform": "github",
          "remediation": {
            "target_branch": "main"
          },
          "github": {
            "labels": ["zeroone-ops", "autofix"],
            "pull_request_assignee_username": "justin"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.platform == "github"
    assert config.github is not None
    assert config.github.labels == ["zeroone-ops", "autofix"]
    assert config.github.pull_request_assignee_username == "justin"


def test_settings_require_remediation_target_branch_for_github_publish_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "platform": "github",
          "github": {
            "labels": ["zeroone-ops"]
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    try:
        load_config()
    except SettingsError as error:
        assert (
            "platform=github remediation publish requires "
            "remediation.target_branch to be configured." in str(error)
        )
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected SettingsError for missing remediation target branch")


def test_settings_require_gitlab_block_for_gitlab_platform(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "platform": "gitlab"
        }
        """.strip(),
        encoding="utf-8",
    )

    try:
        load_config()
    except SettingsError as error:
        assert "platform=gitlab requires a top-level gitlab configuration block." in str(error)
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected SettingsError for missing gitlab block in gitlab mode")


def test_settings_migrate_legacy_review_platform_to_top_level_platform(
    tmp_path: Path,
    monkeypatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "review": {
            "platform": "github"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.platform == "github"
    assert config.gitlab is None
    assert "Deprecated config field `review.platform`" in caplog.text
    assert "Use `platform`" in caplog.text


def test_settings_ignore_legacy_review_platform_when_top_level_platform_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "platform": "github",
          "review": {
            "platform": "gitlab"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.platform == "github"
    assert config.gitlab is None


def test_settings_migrate_legacy_gitlab_target_branch_to_remediation_target_branch(
    tmp_path: Path,
    monkeypatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.chdir(tmp_path)

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

    assert config.remediation.target_branch == "main"
    assert "Deprecated config field `gitlab.target_branch`" in caplog.text
    assert "Use `remediation.target_branch`" in caplog.text


def test_settings_migrate_top_level_validation_commands_to_remediation(
    tmp_path: Path,
    monkeypatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "validation_setup_commands": ["setup-validation"],
          "validation_commands": ["run-validation"],
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.remediation.validation_setup_commands == ["setup-validation"]
    assert config.remediation.validation_commands == ["run-validation"]
    assert "Deprecated top-level remediation config fields" in caplog.text


def test_settings_allow_null_gitlab_block_for_github_platform(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "platform": "github",
          "gitlab": null
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.platform == "github"
    assert config.gitlab is None


def test_settings_require_remediation_target_branch_for_gitlab_platform(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "platform": "gitlab",
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    try:
        load_config()
    except SettingsError as error:
        assert "platform=gitlab requires remediation.target_branch to be configured." in str(error)
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected SettingsError for missing remediation target branch")


def test_settings_allow_solution_artifact_ci_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_WRITE_SOLUTION_ARTIFACTS_IN_CI", "true")

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "execution_mode": "ci",
          "write_solution_artifacts_in_ci": false,
          "base_branch": "main",
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.write_solution_artifacts_in_ci is True


def test_settings_warn_for_deprecated_review_tuning_config(
    tmp_path: Path,
    monkeypatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main"
          },
          "review": {
            "enable_helper_following": false,
            "log_helper_following": true,
            "helper_follow_depth": 1,
            "max_followed_helpers_per_function": 2,
            "max_followed_helper_lines": 80,
            "max_followed_helper_lines_per_review": 160,
            "skip_draft_merge_requests": false
          },
          "gitlab": {
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
    assert config.review.skip_draft_merge_requests is False
    assert config.review.max_context_lines_before == 400
    assert config.review.max_context_lines_after == 400
    assert config.review.inline_comments_enabled is False
    assert "Deprecated review tuning fields are still supported" in caplog.text
    assert "review.enable_helper_following" in caplog.text
    assert "review.max_followed_helper_lines_per_review" in caplog.text
    assert "review.skip_draft_merge_requests" in caplog.text


def test_settings_load_inline_comments_review_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main"
          },
          "review": {
            "inline_comments_enabled": true
          },
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.review.inline_comments_enabled is True


def test_settings_default_gitlab_merge_request_assignee_username_is_none(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.gitlab.merge_request_assignee_username is None


def test_settings_load_gitlab_merge_request_assignee_username(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
            "labels": [],
            "merge_request_assignee_username": "justin"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.gitlab.merge_request_assignee_username == "justin"


def test_settings_load_nested_remediation_and_sonarqube_config(
    tmp_path: Path,
    monkeypatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main",
            "bootstrap_severities": ["LOW", "MEDIUM"],
            "max_retry_count": 2,
            "max_active_work_items": 4,
            "validation_feedback_enabled": true,
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
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.remediation.bootstrap_severities == ["LOW", "MEDIUM"]
    assert config.remediation.max_retry_count == 2
    assert config.remediation.max_active_work_items == 4
    assert config.remediation.validation_feedback_enabled is True
    assert config.remediation.analysis.context_lines_before == 12
    assert config.remediation.analysis.context_lines_after == 18
    assert config.remediation.analysis.max_file_bytes == 1234
    assert config.sonarqube.mock_issues_path == Path("fixtures/sonar/issues.json")
    assert "Deprecated remediation analysis tuning fields are still supported" in caplog.text
    assert "remediation.analysis.context_lines_before" in caplog.text


def test_settings_default_remediation_active_work_item_capacity_is_ten(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.remediation.max_active_work_items == 10
    assert config.remediation.validation_feedback_enabled is False


@pytest.mark.parametrize("capacity", [0, -1])
def test_settings_reject_non_positive_remediation_active_work_item_capacity(
    tmp_path: Path,
    monkeypatch,
    capacity: int,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main",
            "max_active_work_items": CAPACITY
          },
          "gitlab": {
            "labels": []
          }
        }
        """.replace("CAPACITY", str(capacity)).strip(),
        encoding="utf-8",
    )

    try:
        load_config()
    except SettingsError as error:
        assert "max_active_work_items" in str(error)
        assert "greater than or equal to 1" in str(error)
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected SettingsError for non-positive active work item capacity")


def test_settings_load_sarif_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main"
          },
          "sarif": {
            "artifacts": [
              {"path": "artifacts/ruff.sarif", "source_id": "ruff-sarif"},
              {"path": "artifacts/codeql.sarif", "source_id": "codeql-sarif"}
            ]
          },
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert [(artifact.path, artifact.source_id) for artifact in config.sarif.artifacts] == [
        (Path("artifacts/ruff.sarif"), "ruff-sarif"),
        (Path("artifacts/codeql.sarif"), "codeql-sarif"),
    ]


def test_settings_reject_removed_flat_remediation_and_sonar_keys(
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

    try:
        load_config()
    except SettingsError as error:
        assert "Removed flat config keys are no longer supported" in str(error)
        assert "supported_severities" in str(error)
        assert "max_retry_count" in str(error)
        assert "analysis" in str(error)
        assert "mock_sonar_issues_path" in str(error)
    else:  # pragma: no cover - defensive guard
        raise AssertionError("Expected SettingsError for removed flat config keys")


@pytest.mark.parametrize(
    ("config_fragment", "field_name"),
    [
        ('"unknown_root": true,', "unknown_root"),
        ('"review": {"unknown_review": true},', "review.unknown_review"),
        (
            '"remediation": {"target_branch": "main", "unknown_remediation": true},',
            "remediation.unknown_remediation",
        ),
    ],
)
def test_settings_reject_unknown_repository_config_fields(
    tmp_path: Path,
    monkeypatch,
    config_fragment: str,
    field_name: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".zeroone-ops.json").write_text(
        f"""
        {{
          "base_branch": "main",
          {config_fragment}
          "gitlab": {{
            "target_branch": "main",
            "labels": []
          }}
        }}
        """.strip(),
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match=field_name):
        load_config()


def test_settings_keep_legacy_nested_supported_severities_compatible(
    tmp_path: Path,
    monkeypatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "remediation": {
            "target_branch": "main",
            "supported_severities": ["LOW"]
          },
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.remediation.bootstrap_severities == ["LOW"]
    assert "Deprecated config field `remediation.supported_severities`" in caplog.text
    assert "Use `remediation.bootstrap_severities`" in caplog.text


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
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
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
          "remediation": {
            "target_branch": "default"
          },
          "gitlab": {
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
          "remediation": {
            "target_branch": "custom"
          },
          "gitlab": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = load_config()

    assert config.base_branch == "custom"
