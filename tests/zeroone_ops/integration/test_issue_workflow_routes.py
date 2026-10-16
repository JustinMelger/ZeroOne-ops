from pathlib import Path

from zeroone_ops.models.finding import (
    FindingCollectionMetadata,
    FindingCollectionResult,
    NormalizedFinding,
)
from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.state import (
    RunStatus,
)
from zeroone_ops.runner import (
    run_policy,
    run_remediation,
    sync_findings,
)
from zeroone_ops.services.control_plane.policy.github_policy_issue_service import (
    GitHubPolicyIssueProcessResult,
)
from zeroone_ops.services.control_plane.policy.gitlab_policy_issue_service import (
    GitLabPolicyIssueProcessResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service import (
    GitLabFindingSyncResult,
)
from zeroone_ops.services.intake.issue_intake import SyncIssueCollectionResult
from zeroone_ops.services.shared.run_summary_builder import RunSummary


def test_policy_dry_run_returns_github_policy_processing_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "platform": "github",
          "base_branch": "main",
          "validation_commands": [],
          "remediation": {
            "target_branch": "main"
          },
          "github": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.control_plane.policy.github_policy_issue_service."
        "GitHubPolicyIssueService.process_policy",
        lambda self, repository_id, persist=True: GitHubPolicyIssueProcessResult(
            issue=GitHubIssueInfo(
                id=10,
                number=11,
                web_url="https://github.example.com/octo-org/octo-repo/issues/11",
                title="ZeroOne Ops Policy",
                body="",
            ),
            comment_count=3,
            authorized_comment_count=2,
            matched_prefix_count=2,
            accepted_action_count=1,
            rejected_prefix_count=1,
            issue_changed=True,
        ),
    )

    summary = run_policy(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run would process 3 GitHub policy comments" in summary.message
    assert "2 authorized, 2 prefixed, 1 accepted, 1 rejected" in summary.message


def test_policy_dry_run_uses_gitlab_issue_mode_when_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "issues",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.control_plane.policy.gitlab_policy_issue_service."
        "GitLabPolicyIssueService.process_policy",
        lambda self, project_id, persist=True: GitLabPolicyIssueProcessResult(
            issue=GitLabIssueInfo(
                id=10,
                iid=11,
                web_url="https://gitlab.example.com/group/project/-/issues/11",
                title="ZeroOne Ops Policy",
                description="",
            ),
            note_count=3,
            authorized_note_count=2,
            matched_prefix_count=2,
            accepted_action_count=1,
            rejected_prefix_count=1,
            issue_changed=True,
        ),
    )

    summary = run_policy(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run would process 3 GitLab policy notes" in summary.message
    assert "2 authorized, 2 prefixed, 1 accepted, 1 rejected" in summary.message


def test_sync_findings_supports_gitlab_issue_mode_with_empty_inventory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "gitlab": {
            "control_plane_mode": "issues",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    summary = sync_findings(dry_run=True)

    assert summary.status.value == "no_issue"
    assert "No configured finding sources" in summary.message


def test_sync_findings_uses_gitlab_work_items_in_issue_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "gitlab": {
            "control_plane_mode": "issues",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    collection = FindingCollectionResult(
        findings=[
            NormalizedFinding(
                finding_id="ruff:C416:src/service.py:1",
                source_id="ruff-sarif",
                severity="high",
                title="Unnecessary comprehension",
                summary="Use set() directly.",
                repository_path="src/service.py",
                line_start=1,
            )
        ],
        metadata=FindingCollectionMetadata(
            source_id="finding_sync",
            managed_source_ids=["ruff-sarif"],
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.intake.issue_intake.IssueIntakeService.collect_findings_for_sync",
        lambda self, dry_run, run_id: SyncIssueCollectionResult(
            finding_collection=collection,
            issue_count=1,
            message="",
        ),
    )
    policy_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "zeroone_ops.services.control_plane.policy.gitlab_policy_issue_service."
        "GitLabPolicyIssueService.load_policy_state",
        lambda self, project_id, persist: policy_calls.append((project_id, persist)),
    )
    sync_calls: list[tuple[str, int, int, bool]] = []

    def sync_work_items(
        self,
        project_id,
        findings,
        policy_state,
        managed_source_ids,
        max_active_work_items,
        source_priorities,
        persist,
        run_id,
    ):
        del self, policy_state, managed_source_ids, source_priorities, run_id
        sync_calls.append((project_id, len(findings), max_active_work_items, persist))
        return GitLabFindingSyncResult(
            promoted_count=1,
            backlog_only_count=0,
            created_count=0,
            updated_count=0,
            unchanged_count=0,
            demoted_to_candidate_count=0,
            retained_protected_count=0,
            stale_demoted_to_candidate_count=0,
            stale_retained_protected_count=0,
            normalized_severity_counts={"high": 1},
            enabled_severities=("high",),
            backlog_reason_counts={},
        )

    monkeypatch.setattr(
        "zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service."
        "GitLabFindingSyncService.sync",
        sync_work_items,
    )

    summary = sync_findings(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run identified 1 findings eligible under the configured policy" in summary.message
    assert "loaded authoritative work-item indexes but made no changes" in summary.message
    assert policy_calls == [("123", False)]
    assert sync_calls == [("123", 1, 10, False)]


def test_run_remediation_routes_github_to_provider_local_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "platform": "github",
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "remediation": {
            "target_branch": "main"
          },
          "github": {
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def unexpected_load_gitlab_connection_config():  # noqa: ANN202
        raise AssertionError("gitlab config should not load for github remediation")

    monkeypatch.setattr(
        "zeroone_ops.runner.load_gitlab_connection_config",
        unexpected_load_gitlab_connection_config,
    )

    captured: dict[str, object] = {}

    class StubGitHubRemediationRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self, **kwargs: object) -> RunSummary:
            record = kwargs["record"]
            assert hasattr(record, "run_id")
            return RunSummary(
                run_id=record.run_id,
                status=RunStatus.NO_ISSUE,
                message="[ci] No eligible GitHub work items.",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    monkeypatch.setattr(
        "zeroone_ops.services.workflows.remediation_workflow.GitHubRemediationRunner",
        StubGitHubRemediationRunner,
    )

    summary = run_remediation(dry_run=False)
    assert summary.status.value == "no_issue"
    assert summary.message == "[ci] No eligible GitHub work items."
    assert captured["repository_id"] == "octo-org/octo-repo"


def test_run_remediation_routes_gitlab_issue_mode_to_provider_local_runner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "group/project")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "remediation": {
            "target_branch": "main"
          },
          "gitlab": {
            "control_plane_mode": "issues",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    class StubGitLabRemediationRunner:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def run(self, **kwargs: object) -> RunSummary:
            record = kwargs["record"]
            assert hasattr(record, "run_id")
            return RunSummary(
                run_id=record.run_id,
                status=RunStatus.NO_ISSUE,
                message="[ci] No eligible GitLab work items.",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    monkeypatch.setattr(
        "zeroone_ops.services.workflows.remediation_workflow.GitLabRemediationRunner",
        StubGitLabRemediationRunner,
    )

    summary = run_remediation(dry_run=False)

    assert summary.status.value == "no_issue"
    assert summary.message == "[ci] No eligible GitLab work items."
    assert captured["project_id"] == "group/project"
