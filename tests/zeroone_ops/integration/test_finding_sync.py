from pathlib import Path

from zeroone_ops.models.dashboard import DashboardPolicyState, DashboardSeverityPolicyStateEntry
from zeroone_ops.runner import sync_findings, sync_work_item_status
from zeroone_ops.services.control_plane.work_items.github_work_item_lifecycle_service import (
    GitHubWorkItemLifecycleResult,
)


def _unset_sonarqube_environment(monkeypatch) -> None:
    """Keep SARIF-only integration tests independent of local credentials."""
    for name in ("SONARQUBE_URL", "SONARQUBE_TOKEN", "SONARQUBE_PROJECT_KEY"):
        monkeypatch.delenv(name, raising=False)


def _policy_state() -> DashboardPolicyState:
    return DashboardPolicyState(
        severity_policy=[
            DashboardSeverityPolicyStateEntry(severity="low", enabled=False),
            DashboardSeverityPolicyStateEntry(severity="medium", enabled=True),
            DashboardSeverityPolicyStateEntry(severity="high", enabled=True),
        ]
    )


def test_sync_findings_dry_run_collects_sarif_without_gitlab_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _unset_sonarqube_environment(monkeypatch)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "ruff.sarif").write_text(
        """
        {
          "version": "2.1.0",
          "runs": [{
            "tool": {"driver": {"name": "Ruff"}},
            "results": [{
              "ruleId": "E712",
              "level": "warning",
              "message": {"text": "Use direct truthiness instead of == True."},
              "locations": [{"physicalLocation": {
                "artifactLocation": {"uri": "src/service.py"},
                "region": {"startLine": 1}
              }}]
            }]
          }]
        }
        """.strip(),
        encoding="utf-8",
    )
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "platform": "github",
          "base_branch": "main",
          "remediation": {"target_branch": "main"},
          "sarif": {"artifacts": [{"path": "artifacts/ruff.sarif", "source_id": "ruff-sarif"}]},
          "validation_commands": [],
          "github": {"labels": []}
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.control_plane.policy.github_policy_issue_service."
        "GitHubPolicyIssueService.load_policy_state",
        lambda self, repository_id, persist: _policy_state(),
    )

    summary = sync_findings(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run would publish 1 promoted findings as GitHub work items" in summary.message
    assert "0 findings remain backlog-only" in summary.message
    assert "Normalized severities: medium=1." in summary.message
    assert "Promotion policy: enabled=high, medium; backlog reasons: none." in summary.message
    assert "[ci] [ci]" not in summary.message


def test_sync_findings_dry_run_reconciles_empty_managed_sarif_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _unset_sonarqube_environment(monkeypatch)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    (tmp_path / "artifacts").mkdir()
    (tmp_path / "artifacts" / "ruff.sarif").write_text(
        '{"version": "2.1.0", "runs": []}',
        encoding="utf-8",
    )
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "platform": "github",
          "base_branch": "main",
          "remediation": {"target_branch": "main"},
          "sarif": {"artifacts": [{"path": "artifacts/ruff.sarif", "source_id": "ruff-sarif"}]},
          "validation_commands": [],
          "github": {"labels": []}
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.control_plane.policy.github_policy_issue_service."
        "GitHubPolicyIssueService.load_policy_state",
        lambda self, repository_id, persist: _policy_state(),
    )

    summary = sync_findings(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run would publish 0 promoted findings as GitHub work items" in summary.message
    assert "No dashboard-syncable findings found." not in summary.message


def test_work_item_status_dry_run_does_not_load_finding_inventory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    _unset_sonarqube_environment(monkeypatch)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "platform": "github",
          "base_branch": "main",
          "remediation": {"target_branch": "main"},
          "validation_commands": [],
          "github": {"labels": []}
        }
        """.strip(),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def reconcile(self, **kwargs) -> GitHubWorkItemLifecycleResult:
        del self
        captured.update(kwargs)
        return GitHubWorkItemLifecycleResult(
            recovered_stale_claim_count=0,
            demoted_to_candidate_count=0,
            completed_count=0,
            blocked_count=0,
            in_progress_count=0,
            unchanged_count=0,
        )

    monkeypatch.setattr(
        "zeroone_ops.runner.GitHubWorkItemLifecycleService.reconcile",
        reconcile,
    )
    summary = sync_work_item_status(dry_run=True)

    assert summary.status.value == "reconciled"
    assert "Dry-run would reconcile GitHub remediation work items" in summary.message
    assert captured["repository_id"] == "octo-org/octo-repo"
    assert captured["persist"] is False
