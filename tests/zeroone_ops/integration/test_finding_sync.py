from pathlib import Path

import httpx

from zeroone_ops.models.config import GitHubConnectionConfig, GitLabConnectionConfig
from zeroone_ops.models.dashboard import DashboardPolicyState, DashboardSeverityPolicyStateEntry
from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.state import RunStatus
from zeroone_ops.runner import (
    _build_finding_sync_observation,
    _publish_github_operational_summary,
    _publish_gitlab_operational_summary,
    recover_work_item,
    run_remediation,
    sync_findings,
    sync_work_item_status,
)
from zeroone_ops.services.control_plane.overview.github_operational_summary_service import (
    GitHubOperationalSummaryPublishResult,
)
from zeroone_ops.services.control_plane.work_items.github_finding_sync_service import (
    GitHubFindingSyncResult,
)
from zeroone_ops.services.control_plane.work_items.github_work_item_lifecycle_service import (
    GitHubWorkItemLifecycleResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service import (
    GitLabFindingSyncResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_work_item_lifecycle_service import (
    GitLabWorkItemLifecycleResult,
)
from zeroone_ops.services.shared.run_summary_builder import RunSummary


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


def test_publish_github_operational_summary_projects_finding_sync_observation(
    monkeypatch,
) -> None:
    class FakeIssueClient:
        def __init__(self) -> None:
            self.summary_issue: GitHubIssueInfo | None = None

        def find_open_issue(
            self, *, repository_id: str, title: str, labels: list[str] | None = None
        ) -> GitHubIssueInfo | None:
            del repository_id, labels
            if title == "ZeroOne Ops Policy":
                return GitHubIssueInfo(
                    id=1,
                    number=10,
                    web_url="https://github.example.com/octo-org/octo-repo/issues/10",
                    title=title,
                    body="",
                )
            return self.summary_issue

        def create_issue(
            self,
            *,
            repository_id: str,
            title: str,
            body: str,
            labels: list[str] | None = None,
        ) -> GitHubIssueInfo:
            del labels
            self.summary_issue = GitHubIssueInfo(
                id=2,
                number=11,
                web_url=f"https://github.example.com/{repository_id}/issues/11",
                title=title,
                body=body,
            )
            return self.summary_issue

        def update_issue(
            self, *, repository_id: str, issue_number: int, body: str
        ) -> GitHubIssueInfo:
            del repository_id, issue_number
            assert self.summary_issue is not None
            self.summary_issue = self.summary_issue.model_copy(update={"body": body})
            return self.summary_issue

    class FakeWorkItemService:
        def list_open_work_items(self, *, repository_id: str) -> list[object]:
            del repository_id
            return []

        def list_closed_work_items(self, *, repository_id: str) -> list[object]:
            del repository_id
            return []

    issue_client = FakeIssueClient()
    monkeypatch.setattr("zeroone_ops.runner.GitHubPolicyClient", lambda config: issue_client)

    publication = _publish_github_operational_summary(
        github_config=GitHubConnectionConfig(
            api_url="https://api.github.example.com",
            server_url="https://github.example.com",
            token="token",
            repository="octo-org/octo-repo",
        ),
        work_item_service=FakeWorkItemService(),  # type: ignore[arg-type]
        latest_finding_sync=_build_finding_sync_observation(
            GitHubFindingSyncResult(
                promoted_count=2,
                backlog_only_count=3,
                created_count=2,
                updated_count=0,
                unchanged_count=0,
                demoted_to_candidate_count=0,
                retained_protected_count=0,
                stale_demoted_to_candidate_count=0,
                stale_retained_protected_count=0,
                normalized_severity_counts={"high": 2, "medium": 3},
                enabled_severities=("high", "medium"),
                backlog_reason_counts={"severity_disabled": 3},
            )
        ),
    )

    assert publication is not None
    assert publication.action == "created"
    assert "- Findings: `5`" in publication.issue.body
    assert "- Backlog only: `3`" in publication.issue.body
    assert "issues/10" in publication.issue.body


def test_publish_github_operational_summary_ignores_transport_failure(monkeypatch) -> None:
    class FailingIssueClient:
        def find_open_issue(self, **kwargs: object) -> None:
            del kwargs
            request = httpx.Request("GET", "https://api.github.example.com/repos/issues")
            raise httpx.ConnectError("unavailable", request=request)

    class FakeWorkItemService:
        def list_open_work_items(self, *, repository_id: str) -> list[object]:
            del repository_id
            return []

        def list_closed_work_items(self, *, repository_id: str) -> list[object]:
            del repository_id
            return []

    monkeypatch.setattr(
        "zeroone_ops.runner.GitHubPolicyClient",
        lambda config: FailingIssueClient(),
    )

    publication = _publish_github_operational_summary(
        github_config=GitHubConnectionConfig(
            api_url="https://api.github.example.com",
            server_url="https://github.example.com",
            token="token",
            repository="octo-org/octo-repo",
        ),
        work_item_service=FakeWorkItemService(),  # type: ignore[arg-type]
        latest_finding_sync=None,
    )

    assert publication is None


def test_publish_gitlab_operational_summary_projects_observation_and_is_best_effort(
    monkeypatch,
) -> None:
    class FakeIssueClient:
        def __init__(self) -> None:
            self.summary_issue: GitLabIssueInfo | None = None

        def list_open_issues(
            self,
            *,
            project_id: str,
            labels: list[str] | None = None,
        ) -> list[GitLabIssueInfo]:
            assert project_id == "123"
            if labels == ["zeroone-policy"]:
                return [
                    GitLabIssueInfo(
                        id=1,
                        iid=10,
                        web_url="https://gitlab.example.com/group/project/-/issues/10",
                        title="ZeroOne Ops Policy",
                        description="",
                    )
                ]
            return [self.summary_issue] if self.summary_issue is not None else []

        def list_closed_issues(self, **kwargs: object) -> list[GitLabIssueInfo]:
            del kwargs
            return []

        def create_issue(
            self,
            *,
            project_id: str,
            title: str,
            description: str,
            labels: list[str],
        ) -> GitLabIssueInfo:
            assert project_id == "123"
            assert labels == ["zeroone-summary"]
            self.summary_issue = GitLabIssueInfo(
                id=2,
                iid=11,
                web_url="https://gitlab.example.com/group/project/-/issues/11",
                title=title,
                description=description,
            )
            return self.summary_issue

        def update_issue(self, **kwargs: object) -> GitLabIssueInfo:
            del kwargs
            raise AssertionError("The first summary publication should create the issue.")

    class FakeWorkItemService:
        def list_open_work_items(self, *, project_id: str) -> list[object]:
            assert project_id == "123"
            return []

        def list_closed_work_items(self, *, project_id: str) -> list[object]:
            assert project_id == "123"
            return []

    issue_client = FakeIssueClient()
    monkeypatch.setattr("zeroone_ops.runner.GitLabWorkItemClient", lambda config: issue_client)
    config = GitLabConnectionConfig(
        url="https://gitlab.example.com",
        token="token",
        project_id="123",
    )
    publication = _publish_gitlab_operational_summary(
        gitlab_config=config,
        work_item_service=FakeWorkItemService(),  # type: ignore[arg-type]
        latest_finding_sync=_build_finding_sync_observation(
            GitLabFindingSyncResult(
                promoted_count=2,
                backlog_only_count=1,
                created_count=2,
                updated_count=0,
                unchanged_count=0,
                demoted_to_candidate_count=0,
                retained_protected_count=0,
                stale_demoted_to_candidate_count=0,
                stale_retained_protected_count=0,
                normalized_severity_counts={"high": 2, "medium": 1},
                enabled_severities=("high", "medium"),
                backlog_reason_counts={"severity_disabled": 1},
            )
        ),
    )

    assert publication is not None
    assert publication.action == "created"
    assert "## Active Remediation MRs" in publication.issue.description
    assert "- Findings: `3`" in publication.issue.description

    monkeypatch.setattr(
        "zeroone_ops.runner.GitLabWorkItemClient",
        lambda config: _FailingGitLabIssueClient(),
    )
    assert (
        _publish_gitlab_operational_summary(
            gitlab_config=config,
            work_item_service=FakeWorkItemService(),  # type: ignore[arg-type]
            latest_finding_sync=None,
        )
        is None
    )


class _FailingGitLabIssueClient:
    def list_open_issues(self, **kwargs: object) -> list[object]:
        del kwargs
        request = httpx.Request("GET", "https://gitlab.example.com/api/v4/projects/123/issues")
        raise httpx.ConnectError("unavailable", request=request)


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


def test_github_remediation_refreshes_operational_summary_after_execution(
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
          "execution_mode": "ci",
          "platform": "github",
          "base_branch": "main",
          "remediation": {"target_branch": "main"},
          "validation_commands": [],
          "github": {"labels": []}
        }
        """.strip(),
        encoding="utf-8",
    )

    class StubGitHubRemediationRunner:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def run(self, **kwargs: object):
            del kwargs
            return RunSummary(
                run_id="run-1",
                status=RunStatus.FAILED,
                message="[ci] Validation failed.",
                state_path=tmp_path / ".zeroone-ops-state.json",
            )

    captured: dict[str, object] = {}

    def publish_summary(**kwargs: object) -> GitHubOperationalSummaryPublishResult:
        captured.update(kwargs)
        return GitHubOperationalSummaryPublishResult(
            issue=GitHubIssueInfo(
                id=1,
                number=2,
                web_url="https://github.example.com/octo-org/octo-repo/issues/2",
                title="ZeroOne Ops Summary",
                body="",
            ),
            action="updated",
        )

    monkeypatch.setattr("zeroone_ops.runner.GitHubRemediationRunner", StubGitHubRemediationRunner)
    monkeypatch.setattr("zeroone_ops.runner._publish_github_operational_summary", publish_summary)

    summary = run_remediation()

    assert captured["latest_finding_sync"] is None
    assert "Operational summary updated" in summary.message


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
            closed_issue_count=0,
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


def test_work_item_status_routes_gitlab_issue_mode_to_lifecycle_service(
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
          "execution_mode": "ci",
          "base_branch": "main",
          "remediation": {"target_branch": "main"},
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
    captured: dict[str, object] = {}

    def reconcile(self, **kwargs) -> GitLabWorkItemLifecycleResult:
        del self
        captured.update(kwargs)
        return GitLabWorkItemLifecycleResult(
            recovered_stale_claim_count=0,
            demoted_to_candidate_count=0,
            completed_count=0,
            closed_issue_count=0,
            blocked_count=0,
            in_progress_count=0,
            unchanged_count=0,
        )

    monkeypatch.setattr(
        "zeroone_ops.runner.GitLabWorkItemLifecycleService.reconcile",
        reconcile,
    )

    summary = sync_work_item_status(dry_run=True)

    assert summary.status.value == "reconciled"
    assert "Dry-run would reconcile GitLab remediation work items" in summary.message
    assert captured["project_id"] == "group/project"
    assert captured["persist"] is False


def test_recover_work_item_routes_gitlab_issue_mode_to_polling_runner(
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
          "execution_mode": "ci",
          "base_branch": "main",
          "remediation": {"target_branch": "main"},
          "validation_commands": [],
          "gitlab": {"control_plane_mode": "issues", "target_branch": "main", "labels": []}
        }
        """.strip(),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def run(self, **kwargs) -> RunSummary:
        del self
        captured.update(kwargs)
        return RunSummary(
            run_id=kwargs["record"].run_id,
            status=RunStatus.NO_ISSUE,
            message="No recovery commands found.",
            state_path=tmp_path / ".zeroone-ops-state.json",
        )

    monkeypatch.setattr("zeroone_ops.runner.GitLabWorkItemRecoveryRunner.run", run)
    monkeypatch.setattr(
        "zeroone_ops.runner._build_gitlab_policy_issue_service",
        lambda **kwargs: type(
            "PolicyService",
            (),
            {"load_policy_state": lambda self, **kwargs: _policy_state()},
        )(),
    )

    summary = recover_work_item(dry_run=True)

    assert summary.status is RunStatus.NO_ISSUE
    assert captured["project_id"] == "group/project"
    assert captured["active_dry_run"] is True


def test_work_item_status_refreshes_operational_summary_after_live_reconciliation(
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
          "execution_mode": "ci",
          "platform": "github",
          "base_branch": "main",
          "remediation": {"target_branch": "main"},
          "validation_commands": [],
          "github": {"labels": []}
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "zeroone_ops.runner.GitHubWorkItemLifecycleService.reconcile",
        lambda self, **kwargs: GitHubWorkItemLifecycleResult(
            recovered_stale_claim_count=0,
            demoted_to_candidate_count=0,
            completed_count=1,
            closed_issue_count=1,
            blocked_count=0,
            in_progress_count=0,
            unchanged_count=0,
        ),
    )
    captured: dict[str, object] = {}

    def publish_summary(**kwargs: object) -> GitHubOperationalSummaryPublishResult:
        captured.update(kwargs)
        return GitHubOperationalSummaryPublishResult(
            issue=GitHubIssueInfo(
                id=1,
                number=2,
                web_url="https://github.example.com/octo-org/octo-repo/issues/2",
                title="ZeroOne Ops Summary",
                body="",
            ),
            action="updated",
        )

    monkeypatch.setattr("zeroone_ops.runner._publish_github_operational_summary", publish_summary)

    summary = sync_work_item_status()

    assert captured["latest_finding_sync"] is None
    assert "Operational summary updated" in summary.message
