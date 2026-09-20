"""Exercise shared revision execution against real local Git branches."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from zeroone_ops.models.analysis import (
    IssueAnalysis,
    PatchProposal,
    SemanticSafetyAssessment,
    StructuredEditProposal,
    TextEdit,
    ValidationResult,
)
from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.config import AppConfig, GitHubConfig, GitLabConfig, RemediationConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import AppState, FailureDetails, FailureStage, RepositoryState
from zeroone_ops.models.work_item import (
    ChangeRequestRef,
    ProjectedReviewFeedback,
    ProjectedReviewFinding,
    ProjectedReviewState,
    ReviewRevisionRequest,
    WorkItemSourceRef,
    WorkItemState,
)
from zeroone_ops.providers.llm_client import FixtureLLMClient
from zeroone_ops.services.remediation.analysis_service import AnalysisResult
from zeroone_ops.services.remediation.execution_service import ExecutionService
from zeroone_ops.services.remediation.github_remediation_runner import GitHubRemediationRunner
from zeroone_ops.services.remediation.gitlab_remediation_runner import GitLabRemediationRunner
from zeroone_ops.services.shared.branch_manager import BranchManagerError
from zeroone_ops.services.shared.run_state_service import RunStateService
from zeroone_ops.services.shared.state_store import StateStore


def build_config(*, execution_mode="ci"):
    return AppConfig(
        execution_mode=execution_mode,
        base_branch="main",
        gitlab=GitLabConfig(),
        remediation=RemediationConfig(target_branch="main"),
    )


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def revision_repository(tmp_path: Path, *, base_has_target: bool) -> tuple[Path, str]:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.com")
    (root / "AGENTS.md").write_text("Preserve base behavior.\n")
    (root / "src").mkdir()
    if base_has_target:
        (root / "src/service.py").write_text("value = 'base'\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    git(root, "remote", "add", "origin", str(remote))
    git(root, "checkout", "-b", "remediation")
    (root / "src").mkdir(exist_ok=True)
    (root / "src/service.py").write_text("value = 'revision'\n")
    (root / "AGENTS.md").write_text("Preserve revision behavior.\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "revision")
    git(root, "push", "-u", "origin", "remediation")
    sha = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "main")
    return root, sha


def revision_target(sha: str):
    return RemediationExecutionTarget(
        item_id="work-1",
        source_type="ruff-sarif",
        source_ref="finding-1",
        title="Fix service",
        status="review_revision_queued",
        message="Preserve behavior",
        file_path="src/service.py",
        line=1,
    ).model_copy(
        update={
            "revision_branch": "remediation",
            "reviewed_sha": sha,
            "revision_change_request": ChangeRequestRef(
                number=9, web_url="https://example.com/pr/9"
            ),
        }
    )


@pytest.mark.parametrize("base_has_target", [False, True])
@pytest.mark.parametrize("existing_local_branch", [False, True])
def test_revision_reads_checked_out_context_and_pushes_existing_request(
    tmp_path, monkeypatch, base_has_target, existing_local_branch
):
    root, sha = revision_repository(tmp_path, base_has_target=base_has_target)
    if not existing_local_branch:
        git(root, "branch", "-D", "remediation")
    service = ExecutionService(root, build_config(execution_mode="ci"))
    publisher = Mock(side_effect=AssertionError("Must not create or search for a request"))
    monkeypatch.setattr(service.publish_service, "publish", publisher)

    def analyze(*, selected_issue, context, dry_run):
        assert git(root, "rev-parse", "HEAD") == sha
        assert "revision" in context.snippet.content
        assert "base" not in context.snippet.content
        assert "Preserve revision behavior" in context.repository_guidance[0].summary
        (root / "src/service.py").write_text("value = 'corrected'\n")
        return AnalysisResult(
            summary="Corrected revision",
            patch_applied=True,
            validation_passed=True,
            validation_result=ValidationResult(passed=True, results=[], summary="Passed"),
            patch=PatchProposal(
                issue_key=selected_issue.source_ref,
                files_touched=[selected_issue.file_path],
                unified_diff="diff",
                commit_message="chore: revise",
                change_request_title="chore: revise",
                change_request_description="Revise",
            ),
        )

    monkeypatch.setattr(service.analysis_service, "analyze_issue_with_context", analyze)
    result = service.execute_revision(selected_issue=revision_target(sha), dry_run=False)

    assert result.failure is None
    assert result.change_request_action == "updated"
    assert result.published_change_request.iid == 9
    assert git(root, "rev-parse", "origin/remediation") == result.commit_sha
    assert git(root, "rev-parse", "HEAD^") == sha
    assert git(root, "show", "--format=", "--name-only", "HEAD") == "src/service.py"
    publisher.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "unreadable", "drift"])
def test_revision_preparation_failure_never_analyzes(tmp_path, monkeypatch, failure):
    root, sha = revision_repository(tmp_path, base_has_target=False)
    target = revision_target("outdated" if failure == "drift" else sha)
    if failure == "missing":
        target = target.model_copy(update={"file_path": "missing.py"})
    if failure == "unreadable":
        monkeypatch.setattr(
            "zeroone_ops.services.remediation.execution_service.RemediationContextBuilder.build",
            Mock(side_effect=OSError("cannot read")),
        )
    service = ExecutionService(root, build_config(execution_mode="ci"))
    analysis = Mock(side_effect=AssertionError("No model calls expected"))
    monkeypatch.setattr(service.analysis_service, "analyze_issue_with_context", analysis)
    result = service.execute_revision(selected_issue=target, dry_run=False)
    assert result.failure is not None
    assert result.failure.stage == (
        FailureStage.BRANCH_PREPARATION if failure == "drift" else FailureStage.ISSUE_INTAKE
    )
    analysis.assert_not_called()
    assert git(root, "rev-parse", "origin/remediation") == sha


def test_revision_dry_run_does_not_checkout_or_analyze(tmp_path, monkeypatch):
    service = ExecutionService(tmp_path, build_config(execution_mode="ci"))
    checkout = Mock(side_effect=AssertionError("No checkout in dry run"))
    monkeypatch.setattr(service.branch_manager, "checkout_existing_remote_branch", checkout)
    result = service.execute_revision(selected_issue=revision_target("sha"), dry_run=True)
    assert result.failure is None
    checkout.assert_not_called()


@pytest.mark.parametrize("outcome", ["success", "validation", "other_file", "extra_file"])
def test_revision_real_patch_validation_and_scope(tmp_path, monkeypatch, outcome):
    root, sha = revision_repository(tmp_path, base_has_target=False)
    config = build_config()
    config.remediation.max_retry_count = 0
    config.remediation.validation_feedback_enabled = True
    if outcome == "validation":
        config.remediation.validation_commands = ["grep -q revision src/service.py"]
    analysis_path = tmp_path / "analysis.json"
    edit_path = tmp_path / "edit.json"
    analysis_path.write_text(
        IssueAnalysis(
            issue_key="finding-1",
            classification="auto_fixable",
            summary="Revise",
            proposed_strategy="Replace the value",
            target_files=["src/service.py"],
            semantic_safety=SemanticSafetyAssessment(
                current_behavior="Revision value",
                intended_behavior="Corrected value",
                preservation_evidence=["The field remains a string"],
            ),
        ).model_dump_json()
    )
    edit = TextEdit(
        file_path="src/service.py",
        search_text="value = 'revision'",
        replace_text="value = 'corrected'",
    )
    other = TextEdit(
        file_path="AGENTS.md",
        search_text="Preserve revision behavior.",
        replace_text="Changed guidance.",
    )
    edits = (
        [other] if outcome == "other_file" else [edit, other] if outcome == "extra_file" else [edit]
    )
    edit_path.write_text(
        StructuredEditProposal(
            issue_key="finding-1",
            edits=edits,
            commit_message="chore: revise",
            change_request_title="chore: revise",
            change_request_description="Revise value",
        ).model_dump_json()
    )
    service = ExecutionService(root, config)
    monkeypatch.setattr(
        service.analysis_service,
        "_build_llm_client",
        lambda: FixtureLLMClient(analysis_path, structured_edit_fixture_path=edit_path),
    )
    result = service.execute_revision(selected_issue=revision_target(sha), dry_run=False)
    if outcome == "success":
        assert result.failure is None
        assert result.change_request_url == "https://example.com/pr/9"
        assert git(root, "rev-parse", "origin/remediation") == result.commit_sha
    else:
        assert result.failure is not None
        assert git(root, "rev-parse", "HEAD") == sha
        assert git(root, "status", "--porcelain") == ""
        assert (root / "src/service.py").read_text() == "value = 'revision'\n"


def test_revision_rejects_remote_drift_before_push(tmp_path, monkeypatch):
    root, sha = revision_repository(tmp_path, base_has_target=False)
    service = ExecutionService(root, build_config())
    service.branch_manager.checkout_existing_remote_branch(
        branch_name="remediation", expected_head_sha=sha
    )
    remote = tmp_path / "remote.git"
    parent = git(root, "rev-parse", "HEAD^")
    git(remote, "update-ref", "refs/heads/remediation", parent)
    with pytest.raises(BranchManagerError, match="changed during revision"):
        service.branch_manager.push_revision_branch(
            branch_name="remediation", expected_head_sha=sha
        )
    assert git(remote, "rev-parse", "refs/heads/remediation") == parent


class WorkItemStore:
    """Retain native issue identity while exercising real provider-local intake."""

    def __init__(self, work_item):
        self.work_item = work_item
        self.other_work_item = None
        self.issue = SimpleNamespace(
            iid=12, number=12, created_at=None, web_url="https://example.com/issues/12"
        )

    def list_open_work_items(self, **kwargs):
        records = [SimpleNamespace(issue=self.issue, work_item=self.work_item)]
        if self.other_work_item is not None:
            records.append(SimpleNamespace(issue=self.issue, work_item=self.other_work_item))
        return records

    def upsert_work_item(self, *, work_item, **kwargs):
        self.work_item = work_item
        return SimpleNamespace(issue=self.issue, work_item=work_item, action="updated")


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    "outcome", ["success", "context", "semantic", "validation", "push", "closed", "drift"]
)
def test_queued_revision_provider_parity(tmp_path, monkeypatch, platform, outcome):
    root, sha = revision_repository(tmp_path, base_has_target=False)
    config = build_config().model_copy(update={"platform": platform, "github": GitHubConfig()})
    linked = ChangeRequestRef(number=9, web_url="https://example.com/pr/9")
    feedback = ProjectedReviewFeedback(
        summary="Keep the error path",
        finding_count=1,
        findings=[
            ProjectedReviewFinding(
                title="Error swallowed",
                file_path="src/service.py",
                evidence="Returns success",
                explanation="Clients lose errors",
                suggested_follow_up="Preserve the error",
            )
        ],
    )
    store = WorkItemStore(
        WorkItemState(
            work_item_id="work-1",
            kind="remediation",
            status="review_revision_queued",
            source=WorkItemSourceRef(
                source="ruff-sarif", source_item_key="finding-1", repository_scope="org/repo"
            ),
            summary="Fix service",
            file_path="missing.py" if outcome == "context" else "src/service.py",
            line=1,
            linked_change_request=linked,
            projected_review=ProjectedReviewState(
                classification="findings_present",
                reviewed_sha=sha,
                follow_up_required=True,
                feedback=feedback,
            ),
            review_revision_request=ReviewRevisionRequest(
                actor="operator",
                request_reference="comment-1",
                occurred_at="2026-09-19T12:00:00Z",
                reviewed_sha=sha,
            ),
        )
    )
    run_state = RunStateService(
        config=config,
        state_store=StateStore(
            tmp_path / "state.json",
            base_branch="main",
            gitlab_project_id=None,
            sonarqube_project_key=None,
        ),
        state=AppState(repository=RepositoryState(base_branch="main")),
    )
    execution = ExecutionService(root, config)

    def analyze(*, selected_issue, context, dry_run):
        assert outcome not in {"context", "closed", "drift"}
        assert context.prior_review_feedback.findings[0].evidence == "Returns success"
        if outcome == "semantic":
            return AnalysisResult(
                summary="Insufficient evidence",
                validation_passed=False,
                terminal_rejection_stage=FailureStage.SEMANTIC_SAFETY,
            )
        if outcome == "validation":
            return AnalysisResult(
                summary="Validation failed",
                failure=FailureDetails(
                    stage=FailureStage.VALIDATION, message="Regression detected"
                ),
            )
        (root / "src/service.py").write_text("value = 'corrected'\n")
        return AnalysisResult(
            summary="Revised",
            patch_applied=True,
            validation_passed=True,
            validation_result=ValidationResult(passed=True, results=[], summary="Passed"),
            patch=PatchProposal(
                issue_key=selected_issue.source_ref,
                files_touched=["src/service.py"],
                unified_diff="diff",
                commit_message="chore: revise",
                change_request_title="chore: revise",
                change_request_description="Revise",
            ),
        )

    monkeypatch.setattr(execution.analysis_service, "analyze_issue_with_context", analyze)
    monkeypatch.setattr(
        execution.publish_service, "publish", Mock(side_effect=AssertionError("No new request"))
    )
    if outcome == "push":
        monkeypatch.setattr(
            execution.branch_manager,
            "push_current_branch",
            Mock(side_effect=BranchManagerError("Push rejected")),
        )
    runner_class = GitHubRemediationRunner if platform == "github" else GitLabRemediationRunner
    scope = {"repository_id": "org/repo"} if platform == "github" else {"project_id": "org/repo"}
    runner = runner_class(
        repo_root=root,
        config=config,
        work_item_service=store,
        run_state_service=run_state,
        execution_service=execution,
        **scope,
    )
    store.other_work_item = store.work_item.model_copy(
        update={
            "work_item_id": "ordinary-work",
            "status": "approved",
            "severity": "high",
            "linked_change_request": None,
            "projected_review": None,
            "review_revision_request": None,
        }
    )
    runner.change_request_state_lookup = lambda number: ChangeRequestState(
        iid=9,
        web_url=linked.web_url,
        state="closed" if outcome == "closed" else "opened",
        source_branch="remediation",
        head_sha="new-head" if outcome == "drift" else sha,
    )
    runner.run(record=run_state.start_run("revision-run"), active_dry_run=False)
    assert store.work_item.work_item_id == "work-1"
    assert store.work_item.status == (
        "in_progress" if outcome == "success" else "review_feedback_required"
    )
    assert store.work_item.linked_change_request == linked
    assert store.work_item.projected_review.feedback == feedback
    assert store.work_item.claim is None
    assert store.work_item.review_revision_request is None
    assert store.work_item.last_revision_command is not None
    assert store.work_item.last_revision_command.request_reference == "comment-1"
    if outcome != "success":
        assert store.work_item.execution_failure is not None
    else:
        assert git(root, "rev-parse", "origin/remediation") != sha
