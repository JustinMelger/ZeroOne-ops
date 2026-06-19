from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from zeroone_ops.models.remediation import RemediationWorkItem
from zeroone_ops.models.review import (
    CandidateReviewFinding,
    ChangeRequestReviewContext,
    PrecisionAcceptedFinding,
    PrecisionReviewDecision,
)
from zeroone_ops.models.state import (
    FailureStage,
)
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.runner import (
    dashboard_policy,
    dashboard_reconcile,
    dashboard_remediate,
    sync_dashboard_sonar,
)
from zeroone_ops.services.dashboard.dashboard_service import DashboardPolicyProcessResult
from zeroone_ops.services.remediation.analysis_service import AnalysisResult
from zeroone_ops.services.shared.branch_manager import BranchManagerError
from zeroone_ops.services.shared.state_store import StateStore
from zeroone_ops.services.shared.workspace_snapshot import WorkspaceSnapshotService


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
        overlap_packet,
        candidate_stage_summary: str,
        candidate_stage_classification: str,
        candidate_stage_rationale: str,
        max_findings: int,
    ) -> PrecisionReviewDecision:
        del context, overlap_packet, max_findings
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
    assert "Dry-run found 2 SonarQube issues for dashboard sync." in summary.message


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


def test_dashboard_reconcile_dry_run_selects_mr_opened_item(
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
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
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

    def fake_get_merge_request_state(*, project_id: str, merge_request_iid: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": merge_request_iid,
                "web_url": selected_item.merge_request_url,
                "source_branch": selected_item.branch_name,
                "head_sha": selected_item.commit_sha,
                "state": "merged",
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request_state",
        lambda self, **kwargs: fake_get_merge_request_state(**kwargs),
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
    assert summary.mr_url == "https://gitlab.example.com/group/project/-/merge_requests/7"
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
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
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

    def fake_get_merge_request_state(*, project_id: str, merge_request_iid: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": merge_request_iid,
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
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request_state",
        lambda self, **kwargs: fake_get_merge_request_state(**kwargs),
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
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/8",
    )
    merged_item = DashboardItem(
        id="sonar:MERGED",
        source="sonarqube",
        type="code_smell_fix",
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/9",
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

    def fake_get_merge_request_state(*, project_id: str, merge_request_iid: int):  # noqa: ANN202
        del project_id
        item = open_item if merge_request_iid == 8 else merged_item
        state = "opened" if merge_request_iid == 8 else "merged"
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": merge_request_iid,
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
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request_state",
        lambda self, **kwargs: fake_get_merge_request_state(**kwargs),
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
    assert "sonar:MERGED: Merge request !9 was merged." in summary.message
    assert state.dashboard_items["sonar:MERGED"].status == "done"


def test_dashboard_reconcile_ci_reopens_item_when_merge_request_was_closed(
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
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
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

    def fake_get_merge_request_state(*, project_id: str, merge_request_iid: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": merge_request_iid,
                "web_url": selected_item.merge_request_url,
                "source_branch": selected_item.branch_name,
                "head_sha": selected_item.commit_sha,
                "state": "closed",
            },
        )()

    def fake_mark_open(
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
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request_state",
        lambda self, **kwargs: fake_get_merge_request_state(**kwargs),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_open",
        fake_mark_open,
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
    assert state.dashboard_items["sonar:AX123"].status == "open"


def test_dashboard_reconcile_ci_marks_closed_reviewed_item_retry_eligible(
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
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
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

    def fake_get_merge_request_state(*, project_id: str, merge_request_iid: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": merge_request_iid,
                "web_url": selected_item.merge_request_url,
                "source_branch": selected_item.branch_name,
                "head_sha": selected_item.commit_sha,
                "state": "closed",
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request_state",
        lambda self, **kwargs: fake_get_merge_request_state(**kwargs),
    )
    recorded_updates: list[tuple[int | None, bool | None, str | None]] = []

    def fake_mark_open(
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
        del self, project_id, dashboard_item_id, run_id, summary
        recorded_updates.append((retry_count, retry_eligible, retry_block_reason))
        updated_item = selected_item.model_copy(
            update={
                "status": "open",
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
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_open",
        fake_mark_open,
    )

    summary = dashboard_reconcile(dry_run=False)
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()

    assert summary.status.value == "reconciled"
    assert "review-guided retry eligibility" in summary.message
    assert state.dashboard_items["sonar:AX123"].status == "open"
    assert recorded_updates == [(0, True, None)]


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
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
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

    def fake_get_merge_request_state(*, project_id: str, merge_request_iid: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": merge_request_iid,
                "web_url": selected_item.merge_request_url,
                "source_branch": selected_item.branch_name,
                "head_sha": selected_item.commit_sha,
                "state": "closed",
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request_state",
        lambda self, **kwargs: fake_get_merge_request_state(**kwargs),
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
    assert "retry is blocked" in summary.message
    assert state.dashboard_items["sonar:AX123"].status == "failed"
    assert recorded_updates == [(0, False, "Latest review outcome requires manual review.")]


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
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
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

    def fake_get_merge_request_state(*, project_id: str, merge_request_iid: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": merge_request_iid,
                "web_url": selected_item.merge_request_url,
                "source_branch": "other-branch",
                "head_sha": "different",
                "state": "closed",
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request_state",
        lambda self, **kwargs: fake_get_merge_request_state(**kwargs),
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
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
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

    def fake_get_merge_request_state(*, project_id: str, merge_request_iid: int):  # noqa: ANN202
        del project_id
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": merge_request_iid,
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
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request_state",
        lambda self, **kwargs: fake_get_merge_request_state(**kwargs),
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
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
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

    def failing_get_merge_request_state(*, project_id: str, merge_request_iid: int):  # noqa: ANN202
        del project_id, merge_request_iid
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
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request_state",
        lambda self, **kwargs: failing_get_merge_request_state(**kwargs),
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
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/7",
    )
    merged_item = DashboardItem(
        id="sonar:MERGED",
        source="sonarqube",
        type="code_smell_fix",
        status="mr_opened",
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
        merge_request_url="https://gitlab.example.com/group/project/-/merge_requests/8",
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

    def fake_get_merge_request_state(*, project_id: str, merge_request_iid: int):  # noqa: ANN202
        del project_id
        if merge_request_iid == 7:
            raise GitLabClientError("GitLab returned 404")
        return type(
            "GitLabMergeRequestState",
            (),
            {
                "iid": merge_request_iid,
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
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request_state",
        lambda self, **kwargs: fake_get_merge_request_state(**kwargs),
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


def test_dashboard_remediate_ci_success_marks_dashboard_mr_opened(
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

    def mark_mr_opened(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        branch_name: str,
        merge_request_url: str,
        commit_sha: str,
        merge_request_iid: int | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del (
            project_id,
            run_id,
            branch_name,
            merge_request_url,
            commit_sha,
            merge_request_iid,
            retry_count,
            retry_eligible,
            retry_block_reason,
        )
        recorded_updates.append(("mr_opened", dashboard_item_id))
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
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_mr_opened",
        mark_mr_opened,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        lambda self, selected_issue, context, dry_run: type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch applied locally in run. All validation commands passed.",
                "failure": None,
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": "abc123",
                "mr_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
                "mr_action": "created",
                "publish_attempted": True,
                "final_status": None,
            },
        )(),
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "mr_created"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == "zeroone-ops/ax123/service"
    assert summary.commit_sha == "abc123"
    assert summary.mr_url == "https://gitlab.example.com/group/project/-/merge_requests/1"
    assert "Selected dashboard item sonar:AX123 in src/service.py" in summary.message
    assert "Merge request created:" in summary.message
    assert recorded_updates == [("in_progress", "sonar:AX123"), ("mr_opened", "sonar:AX123")]


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

    def mark_mr_opened(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        branch_name: str,
        merge_request_url: str,
        commit_sha: str,
        merge_request_iid: int | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            branch_name,
            merge_request_url,
            commit_sha,
            merge_request_iid,
        )
        recorded_updates.append(("mr_opened", retry_count, retry_eligible, retry_block_reason))
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
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_mr_opened",
        mark_mr_opened,
    )

    def execute_with_context(self, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, dry_run
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
                "mr_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
                "mr_action": "created",
                "publish_attempted": True,
                "final_status": None,
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.remediation.execution_service.ExecutionService.execute_with_context",
        execute_with_context,
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "mr_created"
    assert recorded_updates == [
        ("in_progress", 1, False, None),
        ("mr_opened", 1, False, None),
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
        "zeroone_ops.services.shared.mr_service.MergeRequestService.find_open",
        lambda self, project_id, source_branch, target_branch: None,
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
        lambda self, selected_issue, context, dry_run: type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch applied locally in run. All validation commands passed.",
                "failure": None,
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": "abc123",
                "mr_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
                "mr_action": "created",
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

    assert summary.status.value == "mr_created"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert (
        "Recovered stale in_progress dashboard item before remediation: sonar:AX123."
        in summary.message
    )
    assert updated_statuses == ["open", "in_progress", "mr_opened"]
    assert recovery_logs
    assert "stale in_progress recovery" in recovery_logs[0]
    final_item = current_document.items_by_id()["sonar:AX123"]
    assert final_item.status == "mr_opened"
    assert final_item.last_run_id == state.runs[-1].run_id
    assert final_item.merge_request_url == summary.mr_url
    assert state.active_dashboard_item_id is None


def test_dashboard_remediate_fails_when_mr_opened_update_cannot_persist(
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

    def mark_mr_opened(
        self,
        *,
        project_id: str,
        dashboard_item_id: str,
        run_id: str,
        branch_name: str,
        merge_request_url: str,
        commit_sha: str,
        merge_request_iid: int | None = None,
        retry_count: int | None = None,
        retry_eligible: bool | None = None,
        retry_block_reason: str | None = None,
    ):
        del (
            self,
            project_id,
            dashboard_item_id,
            run_id,
            branch_name,
            merge_request_url,
            commit_sha,
            merge_request_iid,
            retry_count,
            retry_eligible,
            retry_block_reason,
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

    def execute_with_context(self, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Patch applied locally in run. All validation commands passed.",
                "failure": None,
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": "abc123",
                "mr_url": "https://gitlab.example.com/group/project/-/merge_requests/1",
                "mr_action": "created",
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
        "zeroone_ops.services.dashboard.dashboard_remediation_updater.DashboardRemediationUpdater.mark_mr_opened",
        mark_mr_opened,
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
    assert last_run.mr_url == "https://gitlab.example.com/group/project/-/merge_requests/1"


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

    def execute_with_context(self, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
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
                "mr_url": None,
                "mr_action": None,
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
    ):
        del self, project_id, run_id, error_message, retry_count, retry_eligible, retry_block_reason
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

    def execute_with_context(self, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
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
                "mr_url": None,
                "mr_action": None,
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

    def execute_with_context(self, selected_issue, context, dry_run):  # noqa: ANN001
        del self, selected_issue, context, dry_run
        return type(
            "ExecutionResult",
            (),
            {
                "analysis_result": type("AnalysisResult", (), {"summary": "done"})(),
                "status_message": "Local approval rejected the proposed change.",
                "failure": None,
                "branch_name": "zeroone-ops/ax123/service",
                "commit_sha": None,
                "mr_url": None,
                "mr_action": None,
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
        "zeroone_ops.services.shared.branch_manager.BranchManager.build_branch_name",
        lambda self, branch_prefix, issue_key, file_path: "zeroone-ops/ax123/service",
    )
    monkeypatch.setattr(
        "zeroone_ops.services.shared.branch_manager.BranchManager.create_branch",
        lambda self, branch_name: None,
    )

    summary = dashboard_remediate(dry_run=False)

    assert summary.status.value == "rejected"
    assert summary.dashboard_item_id == "sonar:AX123"
    assert summary.branch_name == "zeroone-ops/ax123/service"
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
    ):
        del self, project_id, run_id, error_message, retry_count, retry_eligible, retry_block_reason
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
        "zeroone_ops.services.shared.branch_manager.BranchManager.build_branch_name",
        lambda self, *, branch_prefix, issue_key, file_path: "zeroone-ops/ax123/service",
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
                mr_title="fix: patch service",
                mr_description="summary",
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

    def commit_and_push(self, commit_message: str, *, push: bool = False) -> str:
        del self, commit_message, push
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
    assert summary.branch_name == "zeroone-ops/ax123/service"
    assert summary.commit_sha is None
    assert summary.mr_url is None
    assert "Commit failed: git commit failed" in summary.message
    assert recorded_updates == [("in_progress", "sonar:AX123"), ("failed", "sonar:AX123")]
    assert target_file.read_text(encoding="utf-8") == "value = 1\n"
    assert state.active_dashboard_item_id is None
    assert last_run.failure is not None
    assert last_run.failure.stage == FailureStage.COMMIT
    assert dashboard_state.status == "failed"
    assert dashboard_state.last_run_id == last_run.run_id
    assert dashboard_state.branch_name == "zeroone-ops/ax123/service"
    assert dashboard_state.commit_sha is None
    assert dashboard_state.mr_url is None
    assert dashboard_state.last_error == "Commit failed: git commit failed"
