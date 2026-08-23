"""Safety contracts for copyable CI workflow templates."""

import tomllib
from pathlib import Path
from typing import Any

from pytest import MonkeyPatch
from yaml import safe_load

from zeroone_ops.settings import load_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GITLAB_TEMPLATE_PATH = REPOSITORY_ROOT / "examples/.gitlab-ci.example.yml"
GITLAB_TEMPLATE_CONFIG_PATH = (
    REPOSITORY_ROOT / "tests/zeroone_ops/fixtures/gitlab_ci_template/.zeroone-ops.json"
)
GITHUB_OPERATIONS_TEMPLATE_PATH = REPOSITORY_ROOT / "examples/github-operations.yml"
GITHUB_REVIEW_TEMPLATE_PATH = REPOSITORY_ROOT / "examples/github-review.yml"


def _load_gitlab_template() -> dict[str, Any]:
    """Return the canonical GitLab template as structured YAML."""
    parsed = safe_load(GITLAB_TEMPLATE_PATH.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _gitlab_job(template: dict[str, Any], name: str) -> dict[str, Any]:
    """Return one required GitLab job definition."""
    job = template.get(name)
    assert isinstance(job, dict)
    return job


def _project_version() -> str:
    """Return the package version the canonical template must pin."""
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = project["project"]["version"]
    assert isinstance(version, str)
    return version


def _github_image_reference() -> str:
    """Return the intentionally overridable GitHub template image reference."""
    return (
        "ghcr.io/<owner>/zeroone-ops:"
        f"${{{{ vars.ZERO_ONE_OPS_VERSION || '{_project_version()}' }}}}"
    )


def test_operational_templates_pin_zeroone_image_versions() -> None:
    github_image = _github_image_reference()
    template_expectations = {
        GITHUB_OPERATIONS_TEMPLATE_PATH: (github_image, 5),
        GITHUB_REVIEW_TEMPLATE_PATH: (github_image, 1),
        GITLAB_TEMPLATE_PATH: (
            "ghcr.io/justinmelger/zeroone-ops:${ZERO_ONE_OPS_VERSION}",
            1,
        ),
    }

    for template_path, (image, expected_count) in template_expectations.items():
        template = template_path.read_text(encoding="utf-8")

        assert "zeroone-ops:latest" not in template
        assert template.count(image) == expected_count


def test_gitlab_template_pins_the_current_package_release() -> None:
    template = GITLAB_TEMPLATE_PATH.read_text(encoding="utf-8")
    parsed = _load_gitlab_template()

    assert "zeroone-ops:latest" not in template
    assert parsed["variables"]["ZERO_ONE_OPS_VERSION"] == _project_version()

    base = _gitlab_job(parsed, ".zeroone_ops_base")
    assert base["image"] == {
        "name": "ghcr.io/justinmelger/zeroone-ops:${ZERO_ONE_OPS_VERSION}",
        "entrypoint": [""],
    }


def test_github_operations_uses_trusted_default_branch_checkout() -> None:
    template = GITHUB_OPERATIONS_TEMPLATE_PATH.read_text(encoding="utf-8")

    assert template.count("ref: ${{ github.event.repository.default_branch }}") == 5
    assert "setup and validation commands as executable CI policy" in template


def test_github_operations_template_defines_event_driven_issue_mode_workflows() -> None:
    template = GITHUB_OPERATIONS_TEMPLATE_PATH.read_text(encoding="utf-8")
    parsed = safe_load(template)
    assert isinstance(parsed, dict)
    jobs = parsed["jobs"]
    assert isinstance(jobs, dict)

    findings_sync = jobs["findings-sync"]
    remediate = jobs["remediate"]
    lifecycle = jobs["sync-status"]
    policy = jobs["policy"]
    recovery = jobs["recovery"]

    assert findings_sync["if"] == (
        "github.event_name == 'workflow_dispatch' || github.event_name == 'schedule'"
    )
    assert findings_sync["container"]["image"] == _github_image_reference()
    assert findings_sync["steps"][-1]["run"] == "zeroone-ops findings sync"

    assert remediate["needs"] == "findings-sync"
    assert remediate["container"]["image"] == _github_image_reference()
    assert remediate["steps"][-1]["run"] == "zeroone-ops remediation run"

    assert "pull_request_target" in lifecycle["if"]
    assert lifecycle["container"]["image"] == _github_image_reference()
    assert lifecycle["steps"][-1]["run"] == "zeroone-ops work-items sync-status"

    assert "issue_comment" in policy["if"]
    assert "zeroone-policy" in policy["if"]
    assert policy["steps"][-1]["run"] == "zeroone-ops dashboard policy"

    assert "issue_comment" in recovery["if"]
    assert "zeroone-work-item" in recovery["if"]
    assert recovery["steps"][-1]["run"] == "zeroone-ops work-items recover"


def test_review_template_does_not_run_remediation_validation() -> None:
    template = GITHUB_REVIEW_TEMPLATE_PATH.read_text(encoding="utf-8")
    parsed = safe_load(template)
    assert isinstance(parsed, dict)
    jobs = parsed["jobs"]
    assert isinstance(jobs, dict)
    review = jobs["zeroone-ops-review"]

    assert "validation_setup_commands" not in template
    assert "validation_commands" not in template
    assert "never runs remediation setup or validation commands" in template
    assert review["container"]["image"] == _github_image_reference()
    assert review["steps"][-1]["run"] == "zeroone-ops review"


def test_gitlab_template_documents_protected_privileged_execution() -> None:
    template = GITLAB_TEMPLATE_PATH.read_text(encoding="utf-8")
    base = _gitlab_job(_load_gitlab_template(), ".zeroone_ops_base")

    assert "masked and protected CI/CD variables" in template
    assert "protected default-branch configuration" in template
    assert "setup and validation commands are executable CI policy" in template
    assert "GITLAB_TOKEN" not in base["variables"]
    assert "OPENAI_API_KEY" not in base["variables"]
    assert "zeroone-ops control-plane run" in template
    assert 'OPERATION == "zeroone_ops"' in template
    assert "zeroone_ops_ruff_sarif" in template
    assert "zeroone_ops_mypy_sarif" in template
    assert "artifacts/ruff.sarif" in template
    assert "artifacts/mypy.sarif" in template
    assert 'python "$MYPY_TO_SARIF_SCRIPT"' in template


def test_gitlab_template_defines_the_issue_mode_operational_dag() -> None:
    template = _load_gitlab_template()

    assert "stages" not in template
    assert template["variables"] == {
        "ZERO_ONE_OPS_VERSION": _project_version(),
        "OPERATION": "",
        "ZEROONE_STATIC_CODE_SCAN_DIRECTORIES": ".",
        "ZEROONE_RUFF_SCAN_ENABLED": "true",
        "ZEROONE_MYPY_SCAN_ENABLED": "true",
        "PYTHON_VERSION": "3.13",
        "RUFF_VERSION": "0.14.0",
        "MYPY_VERSION": "1.18.2",
        "MYPY_TO_SARIF_SCRIPT": "scripts/mypy_to_sarif.py",
        "UV_VERSION": "0.11.8",
    }

    ruff = _gitlab_job(template, "zeroone_ops_ruff_sarif")
    mypy = _gitlab_job(template, "zeroone_ops_mypy_sarif")
    findings_sync = _gitlab_job(template, "zeroone_ops_findings_sync")
    control_plane = _gitlab_job(template, "zeroone_ops_control_plane")
    lifecycle = _gitlab_job(template, "zeroone_ops_work_items_sync_status")
    review = _gitlab_job(template, "zeroone_ops_review")

    assert ruff["extends"] == ".zeroone_ruff_scan"
    assert mypy["extends"] == ".zeroone_mypy_scan"
    assert ruff["artifacts"] == {"when": "always", "paths": ["artifacts/ruff.sarif"]}
    assert mypy["artifacts"] == {
        "when": "always",
        "paths": ["artifacts/mypy.json", "artifacts/mypy.sarif"],
    }
    assert (
        'python "$MYPY_TO_SARIF_SCRIPT" artifacts/mypy.json artifacts/mypy.sarif' in mypy["script"]
    )

    assert findings_sync["extends"] == [".zeroone_ops_base", ".zeroone_ops_scheduled"]
    assert findings_sync["needs"] == [
        {"job": "zeroone_ops_work_items_sync_status"},
        {"job": "zeroone_ops_ruff_sarif", "artifacts": True, "optional": True},
        {"job": "zeroone_ops_mypy_sarif", "artifacts": True, "optional": True},
    ]
    assert findings_sync["script"] == ["zeroone-ops findings sync"]
    assert findings_sync["resource_group"] == "zeroone-ops-findings-sync"

    assert control_plane["extends"] == [
        ".zeroone_ops_base",
        ".zeroone_ops_scheduled",
        ".zeroone_ops_remediation_git_setup",
    ]
    assert control_plane["needs"] == [{"job": "zeroone_ops_findings_sync"}]
    assert control_plane["script"] == ["zeroone-ops control-plane run"]
    assert control_plane["resource_group"] == "zeroone-ops-remediation"

    assert lifecycle["extends"] == [".zeroone_ops_base", ".zeroone_ops_scheduled"]
    assert "needs" not in lifecycle
    assert lifecycle["script"] == ["zeroone-ops work-items sync-status"]
    assert lifecycle["resource_group"] == "zeroone-ops-work-items-sync-status"

    assert review["extends"] == ".zeroone_ops_base"
    assert review["script"] == ["zeroone-ops review"]
    assert review["resource_group"] == "zeroone-ops-review"
    assert ".zeroone_ops_remediation_git_setup" not in review["extends"]

    git_setup = _gitlab_job(template, ".zeroone_ops_remediation_git_setup")
    assert (
        'curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh'
        in git_setup["before_script"]
    )


def test_gitlab_template_limits_privileged_jobs_to_default_branch_operations() -> None:
    template = _load_gitlab_template()
    scheduled = _gitlab_job(template, ".zeroone_ops_scheduled")

    assert scheduled["rules"] == [
        {
            "if": (
                "$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && "
                '$CI_PIPELINE_SOURCE == "schedule" && $OPERATION == "zeroone_ops"'
            )
        },
        {
            "if": (
                "$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && "
                '$CI_PIPELINE_SOURCE == "web" && $OPERATION == "zeroone_ops"'
            ),
        },
        {"when": "never"},
    ]

    ruff_scan = _gitlab_job(template, ".zeroone_ruff_scan")
    mypy_scan = _gitlab_job(template, ".zeroone_mypy_scan")
    assert all(
        '$ZEROONE_RUFF_SCAN_ENABLED != "false"' in rule["if"] for rule in ruff_scan["rules"][:2]
    )
    assert all(
        '$ZEROONE_MYPY_SCAN_ENABLED != "false"' in rule["if"] for rule in mypy_scan["rules"][:2]
    )

    review = _gitlab_job(template, "zeroone_ops_review")
    assert review["rules"][0] == {
        "if": '$CI_PIPELINE_SOURCE == "merge_request_event"',
        "allow_failure": True,
    }
    assert review["rules"][-1] == {"when": "never"}


def test_gitlab_template_fixture_matches_configured_sarif_inputs(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(GITLAB_TEMPLATE_CONFIG_PATH))
    monkeypatch.delenv("ZEROONE_OPS_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("ZEROONE_OPS_STATE_PATH", raising=False)

    config = load_config()

    assert config.platform == "gitlab"
    assert config.gitlab.control_plane_mode == "issues"
    assert config.state.path == Path(".zeroone-ops-state.json")
    assert config.openai_solution_output_path == Path("artifacts/openai-solution.json")
    assert [(artifact.path, artifact.source_id) for artifact in config.sarif.artifacts] == [
        (Path("artifacts/ruff.sarif"), "ruff-sarif"),
        (Path("artifacts/mypy.sarif"), "mypy-sarif"),
    ]
