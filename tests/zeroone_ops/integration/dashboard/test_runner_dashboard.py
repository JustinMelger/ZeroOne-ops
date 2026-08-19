from datetime import UTC, datetime, timedelta
from pathlib import Path

from pytest import MonkeyPatch

from zeroone_ops.models.analysis import (
    CodeContextSnippet,
    IssueContext,
    PatchProposal,
    PriorReviewFeedback,
    ValidationResult,
)
from zeroone_ops.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    DashboardSection,
    empty_sections,
)
from zeroone_ops.models.finding import (
    FindingCollectionMetadata,
    FindingCollectionResult,
    NormalizedFinding,
)
from zeroone_ops.models.github import GitHubIssueInfo
from zeroone_ops.models.gitlab import GitLabIssueInfo
from zeroone_ops.models.remediation import RemediationWorkItem
from zeroone_ops.models.review import (
    CandidateReviewFinding,
    ChangeRequestReviewContext,
    PrecisionAcceptedFinding,
    PrecisionReviewDecision,
)
from zeroone_ops.models.state import (
    FailureStage,
    RunStatus,
)
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.runner import (
    dashboard_policy,
    dashboard_reconcile,
    dashboard_remediate,
    run_remediation,
    sync_dashboard_sonar,
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
from zeroone_ops.services.dashboard.dashboard_service import DashboardPolicyProcessResult
from zeroone_ops.services.intake.issue_intake import SyncIssueCollectionResult
from zeroone_ops.services.remediation.analysis_service import AnalysisResult
from zeroone_ops.services.shared.branch_manager import BranchManagerError
from zeroone_ops.services.shared.run_summary_builder import RunSummary
from zeroone_ops.services.shared.state_store import StateStore
from zeroone_ops.services.shared.workspace_snapshot import WorkspaceSnapshotService
from zeroone_ops.utils.git import build_remediation_branch_name

_CANONICAL_SONAR_AX123_BRANCH = build_remediation_branch_name(
    branch_prefix="zeroone-ops",
    source="sonarqube",
    source_reference="AX123",
    file_path="src/service.py",
)


def build_dashboard_document(*, items: list[DashboardItem]) -> DashboardDocument:
    sections = empty_sections()
    sections[0] = DashboardSection(
        key="open_candidates",
        title="Open Candidates",
        items=items,
    )
    return DashboardDocument(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        sections=sections,
    )


class _IntegrationPrecisionClient:
    def review_precision_reconciliation(
        self,
        context: ChangeRequestReviewContext,
        *,
        candidates: list[CandidateReviewFinding],
        candidate_annotations,
        overlap_packet,
        candidate_stage_summary: str,
        candidate_stage_classification: str,
        candidate_stage_rationale: str,
        max_findings: int,
    ) -> PrecisionReviewDecision:
        del context, candidate_annotations, overlap_packet, max_findings
        if candidate_stage_classification == "manual_review_only":
            return PrecisionReviewDecision(
                review_classification="manual_review_only",
                decision_summary=candidate_stage_summary,
                decision_rationale=candidate_stage_rationale,
                accepted_findings=[],
                dropped_candidates=[],
            )
        if not candidates:
            return PrecisionReviewDecision(
                review_classification="no_findings",
                decision_summary="No actionable findings after review validation.",
                decision_rationale=candidate_stage_rationale,
                accepted_findings=[],
                dropped_candidates=[],
            )
        return PrecisionReviewDecision(
            review_classification="findings_present",
            decision_summary=candidate_stage_summary,
            decision_rationale=candidate_stage_rationale,
            accepted_findings=[
                PrecisionAcceptedFinding(
                    source_candidate_ids=[candidate.candidate_id],
                    severity=candidate.severity,
                    file_path=candidate.file_path,
                    line_start=candidate.line_start,
                    line_end=candidate.line_end,
                    symbol=candidate.symbol,
                    issue_kind=candidate.issue_kind,
                    region_hint=candidate.region_hint,
                    title=candidate.title,
                    summary=candidate.title,
                    evidence=[candidate.evidence],
                    why_it_matters=candidate.explanation,
                    recommended_follow_up=candidate.suggested_follow_up,
                )
                for candidate in candidates
            ],
            dropped_candidates=[],
        )


def _install_review_precision_fake(monkeypatch) -> None:
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_reconciliation_service."
        "ReviewReconciliationService._build_llm_client",
        lambda self: _IntegrationPrecisionClient(),
    )


def test_dashboard_remediate_dry_run_returns_no_issue_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        lambda self, project_id, state: type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": None,
                "item_count": 0,
                "message": "No remediation-ready dashboard item found.",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    summary = dashboard_remediate(dry_run=True)

    assert summary.status.value == "no_issue"
    assert "No remediation-ready dashboard item found." in summary.message


def test_dashboard_reconcile_dry_run_returns_no_issue_summary(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_item": None,
                "item_count": 0,
                "message": "No reconciliation-ready dashboard item found.",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )
    summary = dashboard_reconcile(dry_run=True)

    assert summary.status.value == "no_issue"
    assert "No reconciliation-ready dashboard item found." in summary.message


def test_sync_dashboard_sonar_dry_run_collects_broad_inventory_not_remediation_severity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    fixture_path = tmp_path / "issues.json"
    fixture_path.write_text(
        """
        {
          "issues": [
            {
              "key": "LOW",
              "rule": "python:S1481",
              "severity": "MINOR",
              "type": "CODE_SMELL",
              "status": "OPEN",
              "message": "Low severity",
              "component": "sample-project:src/service.py",
              "project": "sample-project",
              "line": 1
            },
            {
              "key": "HIGH",
              "rule": "python:S2259",
              "severity": "CRITICAL",
              "type": "BUG",
              "status": "OPEN",
              "message": "High severity",
              "component": "sample-project:src/service.py",
              "project": "sample-project",
              "line": 2
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    (tmp_path / ".zeroone-ops.json").write_text(
        f"""
        {{
          "base_branch": "main",
          "validation_commands": [],
          "remediation": {{
            "bootstrap_severities": ["LOW"]
          }},
          "gitlab": {{
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }},
          "sonarqube": {{
            "mock_issues_path": "{fixture_path}"
          }}
        }}
        """.strip(),
        encoding="utf-8",
    )

    summary = sync_dashboard_sonar(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run found 2 findings for dashboard sync." in summary.message


def test_dashboard_policy_dry_run_returns_policy_processing_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_service.DashboardService.process_policy",
        lambda self, project_id, persist=True: DashboardPolicyProcessResult(
            document=DashboardDocument(
                issue_id=10,
                issue_iid=11,
                issue_url="https://gitlab.example.com/group/project/-/issues/11",
                title="AI Code Ops Work Queue",
                sections=empty_sections(),
            ),
            note_count=3,
            matched_prefix_count=2,
            accepted_action_count=1,
            rejected_prefix_count=1,
            dashboard_changed=True,
        ),
    )

    summary = dashboard_policy(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run would process 3 dashboard notes" in summary.message
    assert "2 prefixed, 1 accepted, 1 rejected" in summary.message


def test_dashboard_policy_dry_run_returns_github_policy_processing_summary(
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

    summary = dashboard_policy(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run would process 3 GitHub policy comments" in summary.message
    assert "2 authorized, 2 prefixed, 1 accepted, 1 rejected" in summary.message


def test_dashboard_policy_dry_run_uses_gitlab_issue_mode_when_configured(
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

    summary = dashboard_policy(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run would process 3 GitLab policy notes" in summary.message
    assert "2 authorized, 2 prefixed, 1 accepted, 1 rejected" in summary.message


def test_sync_dashboard_sonar_supports_gitlab_issue_mode_with_empty_inventory(
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

    summary = sync_dashboard_sonar(dry_run=True)

    assert summary.status.value == "no_issue"
    assert "No configured finding sources" in summary.message


def test_sync_dashboard_sonar_uses_gitlab_work_items_in_issue_mode(
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
            source_id="dashboard_sync",
            managed_source_ids=["ruff-sarif"],
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.intake.issue_intake.IssueIntakeService.collect_dashboard_sync_issues",
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
        persist,
        run_id,
    ):
        del self, policy_state, managed_source_ids, run_id
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

    summary = sync_dashboard_sonar(dry_run=True)

    assert summary.status.value == "synced"
    assert "Dry-run identified 1 findings eligible under the configured policy" in summary.message
    assert "loaded authoritative work-item indexes but made no changes" in summary.message
    assert policy_calls == [("123", False)]
    assert sync_calls == [("123", 1, 10, False)]


def test_dashboard_reconcile_rejects_gitlab_issue_mode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
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

    summary = dashboard_reconcile(dry_run=True)

    assert summary.status.value == "failed"
    assert "does not support legacy dashboard reconciliation" in summary.message


def test_dashboard_reconcile_dry_run_selects_change_request_opened_item(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/AX123/service",
        commit_sha="abc123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    def fake_get_change_request_state(*, project_id: str, change_request_number: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": change_request_number,
                "web_url": selected_item.merge_request_url,
                "source_branch": selected_item.branch_name,
                "head_sha": selected_item.commit_sha,
                "state": "merged",
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_change_request_state",
        lambda self, **kwargs: fake_get_change_request_state(**kwargs),
    )

    summary = dashboard_reconcile(dry_run=True)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "selected"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == "zeroone-ops/AX123/service"
    assert summary.commit_sha == "abc123"
    assert (
        summary.change_request_url == "https://gitlab.example.com/group/project/-/merge_requests/7"
    )
    assert "Dry-run would reconcile 1 dashboard item: sonar:AX123" in summary.message
    assert state.runs[-1].dashboard_item_id == "sonar:AX123"


def test_dashboard_reconcile_live_run_requires_ci_mode(
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
          "execution_mode": "local",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    summary = dashboard_reconcile(dry_run=False)

    assert summary.status.value == "failed"
    assert "only supported in CI mode" in summary.message


def test_dashboard_reconcile_ci_marks_item_done_when_merge_request_is_merged(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/AX123/service",
        commit_sha="abc123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    def fake_get_change_request_state(*, project_id: str, change_request_number: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": change_request_number,
                "web_url": selected_item.merge_request_url,
                "source_branch": selected_item.branch_name,
                "head_sha": selected_item.commit_sha,
                "state": "merged",
            },
        )()

    def fake_mark_done(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        summary: str | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):  # noqa: ANN202
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            summary,
            retry_count,
            retry_eligible,
            retry_block_reason,
        )
        return type(
            "DashboardRemediationUpdateResult",
            (),
            {"error_message": None, "updated_item": selected_item, "dashboard_issue_url": None},
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_change_request_state",
        lambda self, **kwargs: fake_get_change_request_state(**kwargs),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_done",
        fake_mark_done,
    )

    summary = dashboard_reconcile(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "reconciled"
    assert "was merged" in summary.message
    assert state.dashboard_items["sonar:AX123"].status == "done"


def test_dashboard_reconcile_ci_processes_multiple_selected_items(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    open_item = DashboardItem(
        id="sonar:OPEN",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/open.py",
        summary="Keep review open.",
        priority="low",
        source_reference="AX124",
        file="src/open.py",
        line=10,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/AX124/open",
        commit_sha="open123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/8",
    )
    merged_item = DashboardItem(
        id="sonar:MERGED",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/merged.py",
        summary="Already merged.",
        priority="low",
        source_reference="AX125",
        file="src/merged.py",
        line=11,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/AX125/merged",
        commit_sha="merged123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/9",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_items": [open_item, merged_item],
                "selected_item": open_item,
                "item_count": 2,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    def fake_get_change_request_state(*, project_id: str, change_request_number: int):  # noqa: ANN202
        del project_id
        item = open_item if change_request_number == 8 else merged_item
        state = "opened" if change_request_number == 8 else "merged"
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": change_request_number,
                "web_url": item.merge_request_url,
                "source_branch": item.branch_name,
                "head_sha": item.commit_sha,
                "state": state,
            },
        )()

    def fake_mark_done(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        summary: str | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):  # noqa: ANN202
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            summary,
            retry_count,
            retry_eligible,
            retry_block_reason,
        )
        return type(
            "DashboardRemediationUpdateResult",
            (),
            {"error_message": None, "updated_item": merged_item, "dashboard_issue_url": None},
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_change_request_state",
        lambda self, **kwargs: fake_get_change_request_state(**kwargs),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_done",
        fake_mark_done,
    )

    summary = dashboard_reconcile(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "reconciled"
    assert "checked 2 dashboard items" in summary.message
    assert "1 marked done" in summary.message
    assert "1 still open" in summary.message
    assert "sonar:MERGED: Change request 9 was merged." in summary.message
    assert state.dashboard_items["sonar:MERGED"].status == "done"


def test_dashboard_reconcile_ci_blocks_item_when_merge_request_was_closed(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/AX123/service",
        commit_sha="abc123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    def fake_get_change_request_state(*, project_id: str, change_request_number: int) -> object:  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": change_request_number,
                "web_url": selected_item.merge_request_url,
                "source_branch": selected_item.branch_name,
                "head_sha": selected_item.commit_sha,
                "state": "closed",
            },
        )()

    def fake_mark_failed(
        self: object,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ) -> object:  # noqa: ANN202
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            error_message,
            retry_count,
            retry_eligible,
            retry_block_reason,
        )
        return type(
            "DashboardRemediationUpdateResult",
            (),
            {"error_message": None, "updated_item": selected_item, "dashboard_issue_url": None},
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_change_request_state",
        lambda self, **kwargs: fake_get_change_request_state(**kwargs),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        fake_mark_failed,
    )

    summary = dashboard_reconcile(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "reconciled"
    assert "closed without merge" in summary.message
    assert state.dashboard_items["sonar:AX123"].status == "failed"


def test_dashboard_reconcile_ci_blocks_closed_reviewed_item(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/AX123/service",
        commit_sha="abc123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
        review_status="findings_present",
        review_findings_count=1,
        review_feedback_summary="Ordering changed in a shared path.",
        retry_count=0,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    def fake_get_change_request_state(*, project_id: str, change_request_number: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": change_request_number,
                "web_url": selected_item.merge_request_url,
                "source_branch": selected_item.branch_name,
                "head_sha": selected_item.commit_sha,
                "state": "closed",
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_change_request_state",
        lambda self, **kwargs: fake_get_change_request_state(**kwargs),
    )
    recorded_updates: list[tuple[int | None, bool | None, str | None]] = []

    def fake_mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):  # noqa: ANN202
        del self, project_id, dashboard_item_id, run_id, error_message
        recorded_updates.append((retry_count, retry_eligible, retry_block_reason))
        updated_item = selected_item.model_copy(
            update={
                "status": "failed",
                "retry_count": retry_count,
                "retry_eligible": retry_eligible,
                "retry_block_reason": retry_block_reason,
            }
        )
        return type(
            "DashboardRemediationUpdateResult",
            (),
            {"error_message": None, "updated_item": updated_item, "dashboard_issue_url": None},
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        fake_mark_failed,
    )

    summary = dashboard_reconcile(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "reconciled"
    assert "explicitly requeue" in summary.message
    assert state.dashboard_items["sonar:AX123"].status == "failed"
    assert recorded_updates == [(0, False, "Change request was closed without merge.")]


def test_dashboard_reconcile_ci_blocks_retry_for_manual_review_only(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/AX123/service",
        commit_sha="abc123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
        review_status="manual_review_only",
        review_feedback_summary="The change needs broader human context.",
        retry_count=0,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    def fake_get_change_request_state(*, project_id: str, change_request_number: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": change_request_number,
                "web_url": selected_item.merge_request_url,
                "source_branch": selected_item.branch_name,
                "head_sha": selected_item.commit_sha,
                "state": "closed",
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_change_request_state",
        lambda self, **kwargs: fake_get_change_request_state(**kwargs),
    )
    recorded_updates: list[tuple[int | None, bool | None, str | None]] = []

    def fake_mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):  # noqa: ANN202
        del self, project_id, dashboard_item_id, run_id, error_message
        recorded_updates.append((retry_count, retry_eligible, retry_block_reason))
        updated_item = selected_item.model_copy(
            update={
                "status": "failed",
                "retry_count": retry_count,
                "retry_eligible": retry_eligible,
                "retry_block_reason": retry_block_reason,
            }
        )
        return type(
            "DashboardRemediationUpdateResult",
            (),
            {"error_message": None, "updated_item": updated_item, "dashboard_issue_url": None},
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        fake_mark_failed,
    )

    summary = dashboard_reconcile(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "reconciled"
    assert "explicitly requeue" in summary.message
    assert state.dashboard_items["sonar:AX123"].status == "failed"
    assert recorded_updates == [(0, False, "Change request was closed without merge.")]


def test_dashboard_reconcile_ci_fails_on_ambiguous_closed_merge_request(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/AX123/service",
        commit_sha="abc123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    def fake_get_change_request_state(*, project_id: str, change_request_number: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": change_request_number,
                "web_url": selected_item.merge_request_url,
                "source_branch": "other-branch",
                "head_sha": "different",
                "state": "closed",
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_change_request_state",
        lambda self, **kwargs: fake_get_change_request_state(**kwargs),
    )

    summary = dashboard_reconcile(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "failed"
    assert "no longer matches" in summary.message
    assert state.dashboard_items["sonar:AX123"].status == "failed"


def test_dashboard_reconcile_ci_marks_closed_inactive_sonar_item_done(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/AX123/service",
        commit_sha="abc123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
        upstream_active=False,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    def fake_get_change_request_state(*, project_id: str, change_request_number: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": change_request_number,
                "web_url": selected_item.merge_request_url,
                "source_branch": selected_item.branch_name,
                "head_sha": selected_item.commit_sha,
                "state": "closed",
            },
        )()

    def fake_mark_done(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        summary: str | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):  # noqa: ANN202
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            summary,
            retry_count,
            retry_eligible,
            retry_block_reason,
        )
        return type(
            "DashboardRemediationUpdateResult",
            (),
            {"error_message": None, "updated_item": selected_item, "dashboard_issue_url": None},
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_change_request_state",
        lambda self, **kwargs: fake_get_change_request_state(**kwargs),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_done",
        fake_mark_done,
    )

    summary = dashboard_reconcile(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "reconciled"
    assert "no longer active" in summary.message
    assert state.dashboard_items["sonar:AX123"].status == "done"


def test_dashboard_reconcile_ci_fails_when_merge_request_metadata_is_inaccessible(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/AX123/service",
        commit_sha="abc123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    def failing_get_change_request_state(*, project_id: str, change_request_number: int):  # noqa: ANN202
        del project_id, change_request_number
        raise GitLabClientError("GitLab returned 404")

    def fake_mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):  # noqa: ANN202
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            error_message,
            retry_count,
            retry_eligible,
            retry_block_reason,
        )
        return type(
            "DashboardRemediationUpdateResult",
            (),
            {"error_message": None, "updated_item": selected_item, "dashboard_issue_url": None},
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_change_request_state",
        lambda self, **kwargs: failing_get_change_request_state(**kwargs),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        fake_mark_failed,
    )

    summary = dashboard_reconcile(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "reconciled"
    assert "1 marked failed" in summary.message
    assert "metadata is inaccessible" in summary.message
    assert "Failed items: sonar:AX123" in summary.message
    assert state.dashboard_items["sonar:AX123"].status == "failed"


def test_dashboard_reconcile_ci_marks_missing_branch_item_failed_and_continues_batch(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    broken_item = DashboardItem(
        id="sonar:BROKEN",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/broken.py",
        summary="Broken MR traceability.",
        priority="low",
        source_reference="BROKEN",
        file="src/broken.py",
        line=10,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/BROKEN/service",
        commit_sha="broken123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
    )
    merged_item = DashboardItem(
        id="sonar:MERGED",
        source="sonarqube",
        type="code_smell_fix",
        status="change_request_opened",
        title="python:S1125 in src/merged.py",
        summary="Merged MR should still reconcile.",
        priority="low",
        source_reference="MERGED",
        file="src/merged.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        branch_name="zeroone-ops/MERGED/service",
        commit_sha="merged123",
        change_request_url="https://gitlab.example.com/group/project/-/merge_requests/8",
        upstream_active=False,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_reconciliation_intake.DashboardReconciliationIntakeService.select_item",
        lambda self, project_id: type(
            "DashboardReconciliationIntakeResult",
            (),
            {
                "selected_items": [broken_item, merged_item],
                "item_count": 2,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="ZeroOne Ops Dashboard",
                    sections=empty_sections(),
                ),
            },
        )(),
    )

    def fake_get_change_request_state(*, project_id: str, change_request_number: int):  # noqa: ANN202
        del project_id
        if change_request_number == 7:
            raise GitLabClientError("GitLab returned 404")
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": change_request_number,
                "web_url": merged_item.merge_request_url,
                "source_branch": merged_item.branch_name,
                "head_sha": merged_item.commit_sha,
                "state": "merged",
            },
        )()

    def fake_mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):  # noqa: ANN202
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            error_message,
            retry_count,
            retry_eligible,
            retry_block_reason,
        )
        updated_item = broken_item.model_copy(update={"status": "failed"})
        return type(
            "DashboardRemediationUpdateResult",
            (),
            {"error_message": None, "updated_item": updated_item, "dashboard_issue_url": None},
        )()

    def fake_mark_done(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        summary: str | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):  # noqa: ANN202
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            summary,
            retry_count,
            retry_eligible,
            retry_block_reason,
        )
        updated_item = merged_item.model_copy(update={"status": "done"})
        return type(
            "DashboardRemediationUpdateResult",
            (),
            {"error_message": None, "updated_item": updated_item, "dashboard_issue_url": None},
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_change_request_state",
        lambda self, **kwargs: fake_get_change_request_state(**kwargs),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        fake_mark_failed,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_done",
        fake_mark_done,
    )

    summary = dashboard_reconcile(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "reconciled"
    assert "1 marked done, 0 reopened, 1 marked failed, 0 still open" in summary.message
    assert "Failed items: sonar:BROKEN" in summary.message
    assert state.dashboard_items["sonar:BROKEN"].status == "failed"
    assert state.dashboard_items["sonar:MERGED"].status == "done"


def test_dashboard_remediate_live_run_requires_ci_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "local",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    def unexpected_select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        raise AssertionError("dashboard intake should not run for live local mode")

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        unexpected_select_item,
    )

    summary = dashboard_remediate(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    last_run = state.runs[-1]

    assert summary.status.value == "failed"
    assert "only supported in CI mode" in summary.message
    assert last_run.failure is not None
    assert last_run.failure.stage == FailureStage.ISSUE_INTAKE


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


def test_dashboard_remediate_ci_success_marks_dashboard_change_request_opened(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        lambda self, project_id, state: type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        lambda self, item: type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder.RemediationContextBuilder.build",
        lambda self, work_item: IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        ),
    )
    recorded_updates: list[tuple[str, str]] = []

    def mark_in_progress(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del project_id, run_id, retry_count, retry_eligible, retry_block_reason
        recorded_updates.append(("in_progress", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_change_request_opened(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        branch_name: str,
        change_request_url: str,
        commit_sha: str,
        change_request_number: int | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
        clear_publication_retry: bool = False,
    ):
        del (
            project_id,
            run_id,
            branch_name,
            change_request_url,
            commit_sha,
            change_request_number,
            retry_count,
            retry_eligible,
            retry_block_reason,
            clear_publication_retry,
        )
        recorded_updates.append(("change_request_opened", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_change_request_opened",
        mark_change_request_opened,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        lambda self, selected_issue, context, dry_run, branch_name: type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch applied locally in run. All validation commands passed.",
                "failure": None,
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": "abc123",
                "change_request_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
                "change_request_action": "created",
                "publish_attempted": True,
                "final_status": None,
            },
        )(),
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "change_request_created"
    assert summary.work_item_id == "sonar:AX123"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == "zeroone-ops/ax123/service"
    assert summary.commit_sha == "abc123"
    assert (
        summary.change_request_url == "https://gitlab.example.com/group/project/-/merge_requests/1"
    )
    assert "Selected dashboard item sonar:AX123 in src/service.py" in summary.message
    assert "Change request created:" in summary.message
    assert recorded_updates == [
        ("in_progress", "sonar:AX123"),
        ("change_request_opened", "sonar:AX123"),
    ]


def test_dashboard_remediate_ci_consumes_retry_feedback_when_retry_eligible(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        review_status="findings_present",
        review_findings_count=1,
        review_feedback_summary="Previous MR changed ordering semantics.",
        review_confidence=0.81,
        review_confidence_reason="Grounded in the reviewed diff.",
        reviewed_head_sha="abc123",
        retry_count=0,
        retry_eligible=True,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        lambda self, project_id, state: type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": build_dashboard_document(items=[selected_item]),
                "recovered_stale_item_ids": (),
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder.RemediationContextBuilder.build",
        lambda self, work_item: IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
            prior_review_feedback=PriorReviewFeedback(
                review_status="findings_present",
                review_findings_count=1,
                review_feedback_summary="Previous MR changed ordering semantics.",
                review_confidence=0.81,
                review_confidence_reason="Grounded in the reviewed diff.",
                reviewed_head_sha="abc123",
                retry_count=0,
            ),
        ),
    )
    recorded_updates: list[tuple[str, int | None, bool | None, str | None]] = []

    def mark_in_progress(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del self, project_id, dashboard_item_id, run_id
        recorded_updates.append(("in_progress", retry_count, retry_eligible, retry_block_reason))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_change_request_opened(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        branch_name: str,
        change_request_url: str,
        commit_sha: str,
        change_request_number: int | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
        clear_publication_retry: bool = False,
    ):
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            branch_name,
            change_request_url,
            commit_sha,
            change_request_number,
            clear_publication_retry,
        )
        recorded_updates.append(
            ("change_request_opened", retry_count, retry_eligible, retry_block_reason)
        )
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_change_request_opened",
        mark_change_request_opened,
    )

    def execute_with_context(self, selected_issue, context, dry_run, branch_name):  # noqa: ANN001
        del self, selected_issue, dry_run, branch_name
        assert context.prior_review_feedback is not None
        assert context.prior_review_feedback.review_status == "findings_present"
        assert context.prior_review_feedback.review_feedback_summary == (
            "Previous MR changed ordering semantics."
        )
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch applied locally in run. All validation commands passed.",
                "failure": None,
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": "abc123",
                "change_request_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
                "change_request_action": "created",
                "publish_attempted": True,
                "final_status": None,
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        execute_with_context,
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "change_request_created"
    assert recorded_updates == [
        ("in_progress", 1, False, None),
        ("change_request_opened", 1, False, None),
    ]


def test_dashboard_remediate_ci_recovers_stale_in_progress_item_before_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = True\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    stale_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="in_progress",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
        last_run_id="run-old",
        status_updated_at=datetime.now(UTC) - timedelta(hours=25),
    )
    current_document = build_dashboard_document(items=[stale_item])
    updated_statuses: list[str] = []
    recovery_logs: list[str] = []

    def load_or_create(self, *, project_id: str) -> DashboardDocument:
        del self, project_id
        return current_document

    def upsert_items(self, *, project_id: str, items: list[DashboardItem]) -> DashboardDocument:
        nonlocal current_document
        del self, project_id
        existing = current_document.items_by_id()
        for item in items:
            existing[item.id] = item
            updated_statuses.append(item.status)
            if item.status == "open" and item.log_excerpt is not None:
                recovery_logs.append(item.log_excerpt)
        current_document = build_dashboard_document(items=list(existing.values()))
        return current_document

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_service.DashboardService.load_or_create",
        load_or_create,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_service.DashboardService.upsert_items",
        upsert_items,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.shared.change_request_lookup.GitLabChangeRequestLookup.find_open_change_request",
        lambda self, source_branch, target_branch: None,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        lambda self, item: type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status=item.status,
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )(),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder.RemediationContextBuilder.build",
        lambda self, work_item: IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        lambda self, selected_issue, context, dry_run, branch_name: type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch applied locally in run. All validation commands passed.",
                "failure": None,
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": "abc123",
                "change_request_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
                "change_request_action": "created",
                "publish_attempted": True,
                "final_status": None,
            },
        )(),
    )

    summary = dashboard_remediate(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "change_request_created"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert (
        "Recovered stale in_progress dashboard item before remediation: sonar:AX123."
        in summary.message
    )
    assert updated_statuses == ["open", "in_progress", "change_request_opened"]
    assert recovery_logs
    assert "stale in_progress recovery" in recovery_logs[0]
    final_item = current_document.items_by_id()["sonar:AX123"]
    assert final_item.status == "change_request_opened"
    assert final_item.last_run_id == state.runs[-1].run_id
    assert final_item.merge_request_url == summary.change_request_url
    assert state.active_dashboard_item_id is None


def test_dashboard_remediate_fails_when_change_request_opened_update_cannot_persist(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    def mark_in_progress(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            retry_count,
            retry_eligible,
            retry_block_reason,
        )
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_change_request_opened(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        branch_name: str,
        change_request_url: str,
        commit_sha: str,
        change_request_number: int | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
        clear_publication_retry: bool = False,
    ):
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            branch_name,
            change_request_url,
            commit_sha,
            change_request_number,
            retry_count,
            retry_eligible,
            retry_block_reason,
            clear_publication_retry,
        )
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": None,
                "updated_item": None,
                "error_message": "Dashboard remediation update failed: write conflict",
            },
        )()

    def execute_with_context(self, selected_issue, context, dry_run, branch_name):  # noqa: ANN001
        del self, selected_issue, context, dry_run, branch_name
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch applied locally in run. All validation commands passed.",
                "failure": None,
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": "abc123",
                "change_request_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
                "change_request_action": "created",
                "publish_attempted": True,
                "final_status": None,
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_change_request_opened",
        mark_change_request_opened,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        execute_with_context,
    )

    summary = dashboard_remediate(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    last_run = state.runs[-1]

    assert summary.status.value == "failed"
    assert "Dashboard lifecycle update failed" in summary.message
    assert last_run.failure is not None
    assert last_run.failure.stage == FailureStage.DASHBOARD_UPDATE
    assert (
        last_run.change_request_url == "https://gitlab.example.com/group/project/-/merge_requests/1"
    )


def test_dashboard_remediate_fails_when_failed_update_cannot_persist(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    def mark_in_progress(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            retry_count,
            retry_eligible,
            retry_block_reason,
        )
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
        publication_retry: object | None = None,
    ):
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            error_message,
            retry_count,
            retry_eligible,
            retry_block_reason,
            publication_retry,
        )
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": None,
                "updated_item": None,
                "error_message": "Dashboard remediation update failed: write conflict",
            },
        )()

    def execute_with_context(self, selected_issue, context, dry_run, branch_name):  # noqa: ANN001
        del self, selected_issue, context, dry_run, branch_name
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch failed in run.",
                "failure": type(
                    "Failure",
                    (),
                    {"stage": FailureStage.COMMIT, "message": "Commit failed: git commit failed"},
                )(),
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": None,
                "change_request_url": None,
                "change_request_action": None,
                "publish_attempted": False,
                "final_status": None,
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        mark_failed,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        execute_with_context,
    )

    summary = dashboard_remediate(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    last_run = state.runs[-1]

    assert summary.status.value == "failed"
    assert "Commit failed: git commit failed" in summary.message
    assert "Dashboard lifecycle update failed" in summary.message
    assert last_run.failure is not None
    assert last_run.failure.stage == FailureStage.DASHBOARD_UPDATE


def test_dashboard_remediate_ci_failure_marks_dashboard_failed(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    recorded_updates: list[tuple[str, str]] = []

    def mark_in_progress(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del self, project_id, run_id, retry_count, retry_eligible, retry_block_reason
        recorded_updates.append(("in_progress", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
        publication_retry: object | None = None,
    ):
        del (
            self,
            project_id,
            run_id,
            error_message,
            retry_count,
            retry_eligible,
            retry_block_reason,
            publication_retry,
        )
        recorded_updates.append(("failed", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def execute_with_context(self, selected_issue, context, dry_run, branch_name):  # noqa: ANN001
        del self, selected_issue, context, dry_run, branch_name
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch failed in run.",
                "failure": type(
                    "Failure",
                    (),
                    {"stage": FailureStage.COMMIT, "message": "Commit failed: git commit failed"},
                )(),
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": None,
                "change_request_url": None,
                "change_request_action": None,
                "publish_attempted": False,
                "final_status": None,
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        mark_failed,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        execute_with_context,
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "failed"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == "zeroone-ops/ax123/service"
    assert "Commit failed: git commit failed" in summary.message
    assert recorded_updates == [("in_progress", "sonar:AX123"), ("failed", "sonar:AX123")]


def test_dashboard_remediate_ci_rejection_marks_dashboard_rejected(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    recorded_updates: list[tuple[str, str]] = []

    def mark_in_progress(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del self, project_id, run_id, retry_count, retry_eligible, retry_block_reason
        recorded_updates.append(("in_progress", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_rejected(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        rejection_reason: str,
    ):
        del self, project_id, run_id, rejection_reason
        recorded_updates.append(("rejected", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def execute_with_context(self, selected_issue, context, dry_run, branch_name):  # noqa: ANN001
        del self, selected_issue, context, dry_run, branch_name
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Local approval rejected the proposed change.",
                "failure": None,
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": None,
                "change_request_url": None,
                "change_request_action": None,
                "publish_attempted": False,
                "final_status": type("FinalStatus", (), {"value": "rejected"})(),
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_rejected",
        mark_rejected,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        execute_with_context,
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "rejected"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == "zeroone-ops/ax123/service"
    assert "Local approval rejected the proposed change." in summary.message
    assert recorded_updates == [("in_progress", "sonar:AX123"), ("rejected", "sonar:AX123")]


def test_dashboard_remediate_ci_manual_analysis_marks_dashboard_rejected(
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
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.source_ref,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    recorded_updates: list[tuple[str, str]] = []

    def mark_in_progress(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del self, project_id, run_id, retry_count, retry_eligible, retry_block_reason
        recorded_updates.append(("in_progress", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_rejected(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        rejection_reason: str,
    ):
        del self, project_id, run_id, rejection_reason
        recorded_updates.append(("rejected", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def fake_analyze_issue_with_context(self, *, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
        return AnalysisResult(
            summary="Patch generation skipped because manual review is required.",
            patch=None,
            patch_applied=False,
            validation_passed=False,
        )

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_rejected",
        mark_rejected,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.analysis_service.AnalysisService.analyze_issue_with_context",
        fake_analyze_issue_with_context,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.shared.branch_manager.BranchManager.ensure_ready",
        lambda self: None,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.shared.branch_manager.BranchManager.create_branch",
        lambda self, branch_name: None,
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "rejected"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == _CANONICAL_SONAR_AX123_BRANCH
    assert "manual review is required" in summary.message
    assert recorded_updates == [("in_progress", "sonar:AX123"), ("rejected", "sonar:AX123")]


def test_dashboard_remediate_ci_commit_failure_restores_workspace_and_failed_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    target_file = tmp_path / "src" / "service.py"
    target_file.write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "control_plane_mode": "dashboard",
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    selected_item = DashboardItem(
        id="sonar:AX123",
        source="sonarqube",
        type="code_smell_fix",
        status="open",
        title="python:S1125 in src/service.py",
        summary="Replace boolean equality with direct truthiness.",
        priority="low",
        source_reference="AX123",
        file="src/service.py",
        line=42,
        rule="python:S1125",
        severity="LOW",
    )

    def select_item(self, project_id: str, state):  # noqa: ANN001
        del self, project_id, state
        return type(
            "DashboardIntakeResult",
            (),
            {
                "selected_item": selected_item,
                "item_count": 1,
                "message": "",
                "document": DashboardDocument(
                    issue_id=10,
                    issue_iid=11,
                    issue_url="https://gitlab.example.com/group/project/-/issues/11",
                    title="AI Code Ops Work Queue",
                    sections=empty_sections(),
                ),
            },
        )()

    def normalize(self, item: DashboardItem):
        del self
        return type(
            "NormalizationResult",
            (),
            {
                "work_item": RemediationWorkItem(
                    dashboard_item_id="sonar:AX123",
                    source_type="sonarqube",
                    source_ref="AX123",
                    title=item.title,
                    status="open",
                    message=item.summary,
                    file_path="src/service.py",
                    line=42,
                    rule_id="python:S1125",
                    severity="LOW",
                ),
                "message": "",
            },
        )()

    def build_context(self, work_item: RemediationWorkItem):
        del self
        return IssueContext(
            issue_key=work_item.dashboard_item_id,
            file_path=work_item.file_path,
            line=work_item.line,
            file_size_bytes=10,
            snippet=CodeContextSnippet(start_line=40, end_line=44, content="  42: value = value"),
            full_file_included=True,
            truncated=False,
        )

    recorded_updates: list[tuple[str, str]] = []

    def mark_in_progress(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del self, project_id, run_id, retry_count, retry_eligible, retry_block_reason
        recorded_updates.append(("in_progress", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    def mark_failed(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        error_message: str,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
        publication_retry: object | None = None,
    ):
        del (
            self,
            project_id,
            run_id,
            error_message,
            retry_count,
            retry_eligible,
            retry_block_reason,
            publication_retry,
        )
        recorded_updates.append(("failed", dashboard_item_id))
        return type(
            "UpdateResult",
            (),
            {
                "dashboard_issue_url": "https://gitlab.example.com/group/project/-/issues/11",
                "updated_item": selected_item,
                "error_message": None,
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_intake.DashboardItemIntakeService.select_item",
        select_item,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_item_normalizer.DashboardItemNormalizer.normalize",
        normalize,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.remediation_context_builder.RemediationContextBuilder.build",
        build_context,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_in_progress",
        mark_in_progress,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_failed",
        mark_failed,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.shared.branch_manager.BranchManager.ensure_ready",
        lambda self: None,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.shared.branch_manager.BranchManager.create_branch",
        lambda self, branch_name: None,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.shared.branch_manager.BranchManager.reset_index",
        lambda self: None,
    )

    snapshot = WorkspaceSnapshotService(tmp_path).capture(["src/service.py"])

    def analyze_issue_with_context(self, *, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
        return AnalysisResult(
            summary="Patch applied locally in run. All validation commands passed.",
            patch=PatchProposal(
                issue_key="sonar:AX123",
                files_touched=["src/service.py"],
                unified_diff="diff --git a/src/service.py b/src/service.py\n",
                commit_message="fix(sonar): patch service [AX123]",
                change_request_title="fix: patch service",
                change_request_description="summary",
            ),
            patch_applied=True,
            validation_passed=True,
            validation_result=ValidationResult(
                passed=True,
                results=[],
                summary="All validation commands passed.",
            ),
            workspace_snapshot=snapshot,
        )

    def commit_and_push(
        self,
        commit_message: str,
        *,
        push: bool = False,
        files_to_commit: list[str] | None = None,
    ) -> str:
        del self, commit_message, push, files_to_commit
        target_file.write_text("value = 2\n", encoding="utf-8")
        raise BranchManagerError("git commit failed")

    monkeypatch.setattr(
        "zeroone_ops.services.remediation.analysis_service.AnalysisService.analyze_issue_with_context",
        analyze_issue_with_context,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.shared.branch_manager.BranchManager.commit_and_push",
        commit_and_push,
    )

    summary = dashboard_remediate(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    last_run = state.runs[-1]
    dashboard_state = state.dashboard_items["sonar:AX123"]

    assert summary.status.value == "failed"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == _CANONICAL_SONAR_AX123_BRANCH
    assert summary.commit_sha is None
    assert summary.change_request_url is None
    assert "Commit failed: git commit failed" in summary.message
    assert recorded_updates == [("in_progress", "sonar:AX123"), ("failed", "sonar:AX123")]
    assert target_file.read_text(encoding="utf-8") == "value = 1\n"
    assert state.active_dashboard_item_id is None
    assert last_run.failure is not None
    assert last_run.failure.stage == FailureStage.COMMIT
    assert dashboard_state.status == "failed"
    assert dashboard_state.last_run_id == last_run.run_id
    assert dashboard_state.branch_name == _CANONICAL_SONAR_AX123_BRANCH
    assert dashboard_state.commit_sha is None
    assert dashboard_state.change_request_url is None
    assert dashboard_state.last_error == "Commit failed: git commit failed"
