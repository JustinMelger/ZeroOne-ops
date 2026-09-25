"""Executable contracts for the repository's daily finding workflow."""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
from yaml import safe_load

from zeroone_ops.settings import load_config

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/finding-dogfood.yml"


def _workflow() -> dict[str, Any]:
    return safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _step(identifier: str) -> dict[str, Any]:
    return next(
        step
        for step in _workflow()["jobs"]["finding-sarif"]["steps"]
        if identifier in (step.get("id"), step["name"])
    )


FAKE_SCANNERS = r"""
uv() {
  printf '%s\n' "$*" >> calls
  case "$2" in
    mypy)
      echo '{}'
      if [ "$5" = tests ]; then return "${TEST_SCAN_STATUS:-0}"; fi
      return "${SCAN_STATUS:-0}"
      ;;
    python)
      if [ "${CONVERSION_STATUS:-0}" != 0 ]; then return "$CONVERSION_STATUS"; fi
      if [ "${MISSING_ARTIFACT:-false}" != true ]; then echo '{}' > "$5"; fi
      ;;
    ruff)
      if [ "${MISSING_ARTIFACT:-false}" != true ]; then echo '{}' > artifacts/ruff.sarif; fi
      return "${SCAN_STATUS:-0}"
      ;;
    *) return 99 ;;
  esac
}
uvx() {
  printf '%s\n' "$*" >> calls
  if [ "${MISSING_ARTIFACT:-false}" != true ]; then echo '{}' > artifacts/semgrep.sarif; fi
  return "${SCAN_STATUS:-0}"
}
"""


def _run_scanner(
    tmp_path: Path, identifier: str, **overrides: str
) -> subprocess.CompletedProcess[str]:
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    return subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-eo",
            "pipefail",
            "-c",
            FAKE_SCANNERS + _step(identifier)["run"],
        ],
        cwd=tmp_path,
        env={**os.environ, "INCLUDE_TEST_FINDINGS": "false", **overrides},
        capture_output=True,
        text=True,
        check=False,
    )


def test_workflow_defaults_and_publication_boundary() -> None:
    workflow = _workflow()
    # PyYAML's YAML 1.1 loader interprets the GitHub `on` key as True.
    triggers = workflow[True]
    option = triggers["workflow_dispatch"]["inputs"]["include_test_findings"]
    assert option["type"] == "boolean"
    assert option["default"] is False
    assert triggers["schedule"]
    job = workflow["jobs"]["finding-sarif"]
    assert job["if"] == (
        "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)"
    )
    assert _step("Check out repository")["with"]["ref"] == (
        "${{ github.event.repository.default_branch }}"
    )
    assert workflow["concurrency"] == {
        "group": "zeroone-ops-remediation-${{ github.repository }}",
        "cancel-in-progress": False,
    }
    assert job["env"]["ZEROONE_OPS_CONFIG"] == ".zeroone-ops.json"
    assert "workflow_dispatch" in job["env"]["INCLUDE_TEST_FINDINGS"]
    assert _step("Prepare optional test configuration")["if"] == (
        "github.event_name == 'workflow_dispatch' && inputs.include_test_findings"
    )
    steps = job["steps"]
    publish = _step("Publish promoted GitHub findings")
    assert publish["if"] == "success()"
    assert publish["run"] == "uv run zeroone-ops findings sync"
    assert all(not step.get("continue-on-error") for step in steps)
    for scanner in ("emit_mypy_sarif", "emit_ruff_sarif", "emit_semgrep_sarif"):
        assert steps.index(_step(scanner)) < steps.index(publish)
        assert "if" not in _step(scanner)
    upload = _step("Upload finding SARIF artifacts")
    assert upload["if"] == "always()"
    assert "artifacts/*.sarif" in upload["with"]["path"]
    assert "artifacts/mypy*.json" in upload["with"]["path"]
    ruff = _step("emit_ruff_sarif")["run"]
    assert "ruff check src" in ruff
    assert "--isolated" not in ruff and "--select" not in ruff
    assert "--config auto" in _step("emit_semgrep_sarif")["run"]


@pytest.mark.parametrize("scanner", ["emit_mypy_sarif", "emit_ruff_sarif", "emit_semgrep_sarif"])
@pytest.mark.parametrize("status", [0, 1, 2])
def test_scanner_exit_status_handling(tmp_path: Path, scanner: str, status: int) -> None:
    result = _run_scanner(tmp_path, scanner, SCAN_STATUS=str(status))
    accepted = status == 0 or (status == 1 and scanner != "emit_semgrep_sarif")
    assert (result.returncode == 0) is accepted
    assert f"status {status}" in result.stdout
    if scanner == "emit_mypy_sarif":
        calls = (tmp_path / "calls").read_text()
        assert "--output json src" in calls
        assert "--output json tests" not in calls
        assert ("mypy_to_sarif.py" in calls) is accepted


@pytest.mark.parametrize("scanner", ["emit_mypy_sarif", "emit_ruff_sarif", "emit_semgrep_sarif"])
def test_missing_artifact_fails_step(tmp_path: Path, scanner: str) -> None:
    result = _run_scanner(tmp_path, scanner, MISSING_ARTIFACT="true")
    assert result.returncode != 0


def test_failed_conversion_fails_step(tmp_path: Path) -> None:
    result = _run_scanner(tmp_path, "emit_mypy_sarif", CONVERSION_STATUS="3")
    assert result.returncode == 3
    assert not (tmp_path / "artifacts/mypy.sarif").exists()


@pytest.mark.parametrize("status", [0, 1, 2])
def test_optional_test_scan_is_additive_and_checked(tmp_path: Path, status: int) -> None:
    result = _run_scanner(
        tmp_path, "emit_mypy_sarif", INCLUDE_TEST_FINDINGS="true", TEST_SCAN_STATUS=str(status)
    )
    assert (result.returncode == 0) is (status in (0, 1))
    calls = (tmp_path / "calls").read_text()
    assert "--output json src" in calls
    assert "--output json tests" in calls
    assert (tmp_path / "artifacts/mypy.sarif").exists()
    assert (tmp_path / "artifacts/mypy-tests.sarif").exists() is (status in (0, 1))


def test_optional_config_preserves_root_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = (ROOT / ".zeroone-ops.json").read_text()
    root_config = tmp_path / ".zeroone-ops.json"
    root_config.write_text(original)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    environment_file = tmp_path / "github-env"
    result = subprocess.run(
        ["bash", "-eo", "pipefail", "-c", _step("Prepare optional test configuration")["run"]],
        cwd=tmp_path,
        env={
            **os.environ,
            "ZEROONE_OPS_CONFIG": str(root_config),
            "RUNNER_TEMP": str(runner_temp),
            "GITHUB_ENV": str(environment_file),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    destination = runner_temp / "zeroone-dogfood.json"
    assert environment_file.read_text() == f"ZEROONE_OPS_CONFIG={destination}\n"
    assert root_config.read_text() == original
    generated = json.loads(destination.read_text())
    test_artifact = generated["sarif"]["artifacts"].pop()
    assert generated == json.loads(original)
    assert test_artifact == {
        "path": "artifacts/mypy-tests.sarif",
        "source_id": "mypy-tests-sarif",
        "severity_mapping": {"default": "medium"},
    }
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(destination))
    config = load_config()
    assert config.sarif.artifacts[-1].source_id == "mypy-tests-sarif"
    assert config.sarif.artifacts[-1].severity_mapping == {"default": "medium"}
    assert config.remediation.max_active_work_items == 5
