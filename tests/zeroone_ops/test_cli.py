import json
import subprocess
import sys
from pathlib import Path

import pytest
from pytest import MonkeyPatch
from typer.testing import CliRunner

from zeroone_ops.cli import app, main
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.shared.run_summary_builder import RunSummary
from zeroone_ops.settings import SettingsError

_RUNNER = CliRunner()


@pytest.mark.parametrize("command", ["sonar", "remediate", "reconcile", "policy"])
def test_dashboard_commands_are_removed(command: str) -> None:
    result = _RUNNER.invoke(app, ["dashboard", command, "--dry-run"])
    assert result.exit_code == 2
    assert "No such command" in result.output


def test_policy_run_delegates_to_neutral_runner(monkeypatch: MonkeyPatch) -> None:
    summary = RunSummary(
        run_id="run-1",
        status=RunStatus.SYNCED,
        message="Policy processed.",
        state_path=Path("state.json"),
    )
    monkeypatch.setattr("zeroone_ops.cli.run_policy", lambda *, dry_run: summary)
    result = _RUNNER.invoke(app, ["policy", "run", "--dry-run"])
    assert result.exit_code == 0
    assert "Policy processed." in result.output


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    "command",
    [
        ["review"],
        ["findings", "sync"],
        ["policy", "run"],
        ["remediation", "run"],
        ["work-items", "recover"],
        ["work-items", "sync-status"],
    ],
)
def test_cli_rejects_dashboard_history_before_provider_access(
    tmp_path, monkeypatch, platform, command
):
    config_path = tmp_path / ".zeroone-ops.json"
    state_path = tmp_path / "state.json"
    config = {
        "platform": platform,
        "base_branch": "main",
        "remediation": {"target_branch": "main"},
        "state": {"path": str(state_path)},
    }
    if platform == "gitlab":
        config["gitlab"] = {"control_plane_mode": "issues"}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    content = json.dumps({"dashboard_items": {"private-identifier": {"secret": "private-content"}}})
    state_path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(config_path))
    monkeypatch.setenv("ZEROONE_OPS_STATE_PATH", str(state_path))
    result = subprocess.run(
        [sys.executable, "-m", "zeroone_ops.cli", *command, "--dry-run"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "State migration required:" in result.stderr
    assert "docs/migration-v1.md" in result.stderr
    assert "Traceback" not in result.stderr
    assert "private-identifier" not in result.stderr
    assert "private-content" not in result.stderr
    assert state_path.read_text(encoding="utf-8") == content


def test_cli_rejects_retired_mode_with_configuration_guidance(tmp_path, monkeypatch):
    config_path = tmp_path / ".zeroone-ops.json"
    config_path.write_text(
        json.dumps(
            {
                "base_branch": "main",
                "platform": "gitlab",
                "gitlab": {"control_plane_mode": "dashboard"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(config_path))
    result = subprocess.run(
        [sys.executable, "-m", "zeroone_ops.cli", "policy", "run", "--dry-run"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "gitlab.control_plane_mode" in result.stderr
    assert "docs/migration-v1.md" in result.stderr
    assert "Traceback" not in result.stderr


def test_remediation_run_prints_neutral_work_item_summary(monkeypatch: MonkeyPatch) -> None:
    """The canonical remediation command exposes the neutral work-item identifier."""
    summary = RunSummary(
        run_id="run-1",
        status=RunStatus.NO_ISSUE,
        message="[ci] No remediation work item is eligible.",
        state_path=Path(".zeroone-ops-state.json"),
        work_item_id="work-item-1",
    )
    monkeypatch.setattr("zeroone_ops.cli.run_remediation", lambda *, dry_run: summary)

    result = _RUNNER.invoke(app, ["remediation", "run", "--dry-run"])

    assert result.exit_code == 0
    assert "work_item_id=work-item-1" in result.output


def test_control_plane_run_prints_combined_workflow_summary(monkeypatch: MonkeyPatch) -> None:
    """The combined control-plane command uses the shared CLI summary contract."""
    summary = RunSummary(
        run_id="run-1",
        status=RunStatus.NO_ISSUE,
        message="[ci] No remediation work item is eligible.",
        state_path=Path(".zeroone-ops-state.json"),
    )
    monkeypatch.setattr(
        "zeroone_ops.cli.run_gitlab_issue_control_plane",
        lambda *, dry_run: summary,
    )

    result = _RUNNER.invoke(app, ["control-plane", "run", "--dry-run"])

    assert result.exit_code == 0
    assert "status=no_issue" in result.output
    assert "No remediation work item is eligible." in result.output


def test_work_items_sync_status_prints_lifecycle_summary(monkeypatch: MonkeyPatch) -> None:
    """The provider-neutral lifecycle command uses the shared CLI summary format."""
    summary = RunSummary(
        run_id="run-1",
        status=RunStatus.RECONCILED,
        message="[ci] Reconciled GitHub remediation work items.",
        state_path=Path(".zeroone-ops-state.json"),
    )
    monkeypatch.setattr("zeroone_ops.cli.sync_work_item_status", lambda *, dry_run: summary)

    result = _RUNNER.invoke(app, ["work-items", "sync-status", "--dry-run"])

    assert result.exit_code == 0
    assert "Deprecated command" not in result.output
    assert "status=reconciled" in result.output
    assert "Reconciled GitHub remediation work items." in result.output


def test_work_items_recover_prints_recovery_summary(monkeypatch: MonkeyPatch) -> None:
    """The recovery command keeps the shared CLI summary contract."""
    summary = RunSummary(
        run_id="run-1",
        status=RunStatus.SYNCED,
        message="[ci] Processed 1 GitHub work-item comments.",
        state_path=Path(".zeroone-ops-state.json"),
        work_item_id="work-item-1",
    )
    monkeypatch.setattr("zeroone_ops.cli.recover_work_item", lambda *, dry_run: summary)

    result = _RUNNER.invoke(app, ["work-items", "recover", "--dry-run"])

    assert result.exit_code == 0
    assert "status=synced" in result.output
    assert "work_item_id=work-item-1" in result.output


def test_main_renders_settings_error_without_traceback(
    monkeypatch: MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Repository config errors remain fatal but are concise for CI operators."""

    def raise_settings_error() -> None:
        raise SettingsError("Invalid configuration: review.unsupported_option: unknown field")

    monkeypatch.setattr("zeroone_ops.cli.app", raise_settings_error)

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert capsys.readouterr().err == (
        "Configuration error: Invalid configuration: review.unsupported_option: unknown field\n"
    )


@pytest.mark.parametrize(
    ("extra_config", "problem"),
    [
        ({"unknown_option": True}, "unknown_option: unknown field"),
        *[
            (
                config,
                f"{field}: removed in v1; use {replacement} instead. See docs/migration-v1.md",
            )
            for config, field, replacement in (
                ({"review": {"platform": "retired-secret"}}, "review.platform", "platform"),
                (
                    {"gitlab": {"target_branch": "retired-secret"}},
                    "gitlab.target_branch",
                    "remediation.target_branch",
                ),
                (
                    {"remediation": {"supported_severities": ["retired-secret"]}},
                    "remediation.supported_severities",
                    "remediation.bootstrap_severities",
                ),
                (
                    {"validation_setup_commands": ["retired-secret"]},
                    "validation_setup_commands",
                    "remediation.validation_setup_commands",
                ),
                (
                    {"validation_commands": ["retired-secret"]},
                    "validation_commands",
                    "remediation.validation_commands",
                ),
            )
        ],
        *[
            (
                {"review": {field: value}},
                f"review.{field}: removed in v1 because it had no effect; "
                "remove this field. See docs/migration-v1.md",
            )
            for field, value in (
                ("max_review_feedback_retries", 1),
                ("skip_draft_merge_requests", True),
            )
        ],
    ],
)
def test_module_entrypoint_reports_invalid_config_without_traceback(
    tmp_path: Path, extra_config: dict[str, object], problem: str
) -> None:
    """The installed process entrypoint exits cleanly for strict config failures."""
    (tmp_path / ".zeroone-ops.json").write_text(
        json.dumps({"platform": "github", "base_branch": "main", **extra_config}),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "-m", "zeroone_ops.cli", "findings", "sync"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == f"Configuration error: Invalid configuration: {problem}\n"
    assert "Traceback" not in completed.stderr
    assert "retired-secret" not in completed.stderr
