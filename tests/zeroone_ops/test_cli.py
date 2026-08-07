from pathlib import Path

from pytest import MonkeyPatch
from typer.testing import CliRunner

from zeroone_ops.cli import app
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.shared.run_summary_builder import RunSummary

_RUNNER = CliRunner()


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


def test_dashboard_remediate_remains_an_alias_for_neutral_remediation(
    monkeypatch: MonkeyPatch,
) -> None:
    """The legacy GitLab command keeps using the canonical runner entrypoint."""
    summary = RunSummary(
        run_id="run-1",
        status=RunStatus.NO_ISSUE,
        message="[ci] No dashboard item is eligible.",
        state_path=Path(".zeroone-ops-state.json"),
        work_item_id="sonarqube:AX123",
        dashboard_item_id="sonarqube:AX123",
    )
    monkeypatch.setattr("zeroone_ops.cli.run_remediation", lambda *, dry_run: summary)

    result = _RUNNER.invoke(app, ["dashboard", "remediate", "--dry-run"])

    assert result.exit_code == 0
    assert "Deprecated command `zeroone-ops dashboard remediate`" in result.output
    assert "Use `zeroone-ops remediation run`" in result.output
    assert "work_item_id=sonarqube:AX123" in result.output
    assert "dashboard_item_id=sonarqube:AX123" in result.output


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


def test_dashboard_sonar_warns_about_the_canonical_findings_command(
    monkeypatch: MonkeyPatch,
) -> None:
    """The legacy findings command gives operators a direct migration path."""
    summary = RunSummary(
        run_id="run-1",
        status=RunStatus.SYNCED,
        message="[ci] Synced findings.",
        state_path=Path(".zeroone-ops-state.json"),
    )
    monkeypatch.setattr("zeroone_ops.cli.sync_findings", lambda *, dry_run: summary)

    result = _RUNNER.invoke(app, ["dashboard", "sonar", "--dry-run"])

    assert result.exit_code == 0
    assert "Deprecated command `zeroone-ops dashboard sonar`" in result.output
    assert "Use `zeroone-ops findings sync`" in result.output


def test_dashboard_reconcile_warns_about_the_canonical_lifecycle_command(
    monkeypatch: MonkeyPatch,
) -> None:
    """The legacy lifecycle command gives operators a direct migration path."""
    summary = RunSummary(
        run_id="run-1",
        status=RunStatus.RECONCILED,
        message="[ci] Reconciled GitLab remediation work items.",
        state_path=Path(".zeroone-ops-state.json"),
    )
    monkeypatch.setattr("zeroone_ops.cli.dashboard_reconcile", lambda *, dry_run: summary)

    result = _RUNNER.invoke(app, ["dashboard", "reconcile", "--dry-run"])

    assert result.exit_code == 0
    assert "Deprecated command `zeroone-ops dashboard reconcile`" in result.output
    assert "Use `zeroone-ops work-items sync-status`" in result.output
