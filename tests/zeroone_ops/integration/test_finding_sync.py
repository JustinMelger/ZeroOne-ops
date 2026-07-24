from pathlib import Path

from zeroone_ops.models.dashboard import DashboardPolicyState, DashboardSeverityPolicyStateEntry
from zeroone_ops.runner import sync_findings


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
          "sarif": {"artifact_paths": ["artifacts/ruff.sarif"]},
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
