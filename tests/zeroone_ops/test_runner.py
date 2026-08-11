"""Focused tests for runner-level composition boundaries."""

from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch

from zeroone_ops import runner
from zeroone_ops.models.state import RunStatus
from zeroone_ops.services.shared.run_summary_builder import RunSummary


def test_gitlab_issue_control_plane_refreshes_summary_once(monkeypatch: MonkeyPatch) -> None:
    """The combined GitLab job defers component projections until completion."""
    config = SimpleNamespace(dry_run=False)
    synced_summary = RunSummary(
        run_id="run-1",
        status=RunStatus.SYNCED,
        message="[ci] Control-plane state synchronized.",
        state_path=Path(".zeroone-ops-state.json"),
    )
    remediation_summary = RunSummary(
        run_id="run-1",
        status=RunStatus.NO_ISSUE,
        message="[ci] No remediation work item is eligible.",
        state_path=Path(".zeroone-ops-state.json"),
    )
    component_calls: list[tuple[str, bool]] = []
    publication_calls: list[object] = []

    monkeypatch.setattr("zeroone_ops.runner.load_config", lambda: config)
    monkeypatch.setattr("zeroone_ops.runner._gitlab_issue_mode_is_active", lambda _: True)
    monkeypatch.setattr(
        "zeroone_ops.runner.dashboard_policy",
        lambda *, dry_run, publish_operational_summary: (
            component_calls.append(("policy", publish_operational_summary)) or synced_summary
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.runner.recover_work_item",
        lambda *, dry_run, publish_operational_summary: (
            component_calls.append(("recovery", publish_operational_summary)) or synced_summary
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.runner.run_remediation",
        lambda *, dry_run, publish_operational_summary: (
            component_calls.append(("remediation", publish_operational_summary))
            or remediation_summary
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.runner._refresh_gitlab_operational_summary",
        lambda: publication_calls.append(object()) or "",
    )

    result = runner.run_gitlab_issue_control_plane()

    assert result == remediation_summary
    assert component_calls == [
        ("policy", False),
        ("recovery", False),
        ("remediation", False),
    ]
    assert len(publication_calls) == 1
