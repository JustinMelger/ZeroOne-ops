"""Verify review-context lookup remains outside skipped and dry-run routes."""

from unittest.mock import Mock

import pytest

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    ChangeRequestChangedFile,
    ChangeRequestReviewCandidate,
    PrecisionReviewDecision,
    ReviewResult,
)
from zeroone_ops.models.state import ChangeRequestReviewState, FailureStage, RunStatus
from zeroone_ops.services.review.context.remediation_review_context_resolver import (
    RemediationReviewContextResolver,
)
from zeroone_ops.services.review.pipeline.review_candidate_generation_service import (
    ReviewCandidateGenerationService,
)
from zeroone_ops.services.review.pipeline.review_reconciliation_service import (
    ReviewReconciliationService,
)
from zeroone_ops.services.review.pipeline.review_runner import LOGGER, ReviewRunner
from zeroone_ops.services.review.state.review_state_service import ReviewStateService
from zeroone_ops.services.shared.state_store import StateStore


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize("mode", ["dry_run", "no_selection", "context_failure", "same_sha"])
def test_review_routes_skip_verified_context_lookup(tmp_path, monkeypatch, platform, mode):
    monkeypatch.chdir(tmp_path)
    config = AppConfig.model_validate(
        {
            "platform": platform,
            "base_branch": "main",
            platform: {},
            "remediation": {"target_branch": "main"},
        }
    )
    source = tmp_path / "src" / "service.py"
    source.parent.mkdir()
    source.write_text("value = 2\n")
    change = ChangeRequestReviewCandidate(
        change_request_number=9,
        title="Review",
        source_branch="fix",
        target_branch="main",
        head_sha="current",
        web_url="https://example/pr/9",
        changes=[]
        if mode == "context_failure"
        else [
            ChangeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -1 +1 @@\n-value = 1\n+value = 2\n",
            )
        ],
    )
    client = Mock()
    client.get_change_request.return_value = change
    client.list_change_request_comments.return_value = []
    client.get_current_user_username.return_value = "bot"
    client.allows_machine_safe_comment_fallback.return_value = False
    store = StateStore(
        tmp_path / "state.json",
        base_branch="main",
        gitlab_project_id=None,
        sonarqube_project_key=None,
    )
    state_service = ReviewStateService(store, store.load())
    if mode == "same_sha":
        state_service.state.reviews["9:current"] = ChangeRequestReviewState(
            change_request_number=9,
            head_sha="current",
            status="no_findings",
            last_run_id="earlier",
            summary="Already reviewed",
        )
    model = Mock()
    model.review_merge_request.return_value = ReviewResult(
        classification="no_findings", summary="No findings"
    )
    model.review_precision_reconciliation.return_value = PrecisionReviewDecision(
        review_classification="no_findings",
        decision_summary="No findings",
        decision_rationale="No candidates",
    )
    for stage in (ReviewCandidateGenerationService, ReviewReconciliationService):
        monkeypatch.setattr(stage, "_build_llm_client", lambda self: model)
    lookup = Mock(side_effect=AssertionError("Verified context lookup must not run"))
    runner = ReviewRunner(
        repo_root=tmp_path,
        config=config,
        review_client=client,
        review_state_service=state_service,
        remediation_context_resolver=RemediationReviewContextResolver(lookup=lookup, logger=LOGGER),
    )

    summary = runner.run(
        repository_id="org/repo",
        current_change_request_number=None if mode == "no_selection" else 9,
        triggered_head_sha=None,
        run_id="run",
        record=state_service.start_run("run"),
        active_dry_run=mode == "dry_run",
    )

    lookup.assert_not_called()
    expected = {
        "dry_run": RunStatus.REVIEWED,
        "same_sha": RunStatus.REVIEWED,
        "context_failure": RunStatus.FAILED,
        "no_selection": RunStatus.NO_ISSUE,
    }
    assert summary.status == expected[mode]
    if mode == "context_failure":
        assert state_service.state.runs[-1].failure.stage == FailureStage.REVIEW_CONTEXT
    if mode == "same_sha":
        assert "No new changes after the last review" in summary.message
    client.create_change_request_comment.assert_not_called()
    client.update_change_request_comment.assert_not_called()
    client.create_change_request_inline_comment.assert_not_called()
