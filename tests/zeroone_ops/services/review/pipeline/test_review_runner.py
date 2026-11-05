"""Verify review routing and verified overview publication."""

from unittest.mock import Mock

import pytest

from zeroone_ops.models.change_request import ChangeRequestState
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    ChangeRequestChangedFile,
    ChangeRequestReviewCandidate,
    PrecisionReviewDecision,
    ReviewComment,
    ReviewResult,
)
from zeroone_ops.models.state import ChangeRequestReviewState, FailureStage, RunStatus
from zeroone_ops.services.review.context.remediation_review_context_resolver import (
    RemediationReviewContextResolver,
)
from zeroone_ops.services.review.continuity.review_continuity_context_service import (
    ReviewContinuityContextService,
)
from zeroone_ops.services.review.continuity.review_projection_repair_service import (
    ReviewProjectionRepairService,
)
from zeroone_ops.services.review.pipeline.review_candidate_generation_service import (
    ReviewCandidateGenerationService,
)
from zeroone_ops.services.review.pipeline.review_reconciliation_service import (
    ReviewReconciliationService,
)
from zeroone_ops.services.review.pipeline.review_runner import LOGGER, ReviewRunner
from zeroone_ops.services.review.publish.review_overview_codec import decode_overview
from zeroone_ops.services.review.state.review_state_service import ReviewStateService
from zeroone_ops.services.shared.state_store import StateStore


@pytest.mark.parametrize("platform", ["github", "gitlab"])
@pytest.mark.parametrize(
    "mode", ["dry_run", "no_selection", "context_failure", "same_sha", "publish"]
)
def test_review_routes_limit_verified_context_lookup(tmp_path, monkeypatch, platform, mode):
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
    comments: list[ReviewComment] = []
    client.list_change_request_comments.side_effect = lambda **kwargs: list(comments)
    client.get_current_user_username.return_value = "bot"
    client.allows_machine_safe_comment_fallback.return_value = False
    if mode == "publish":
        client.get_change_request_state.return_value = ChangeRequestState(
            iid=9,
            state="opened",
            source_branch="fix",
            web_url=change.web_url,
            head_sha=change.head_sha,
        )

        def create_comment(**kwargs) -> ReviewComment:
            note = ReviewComment(
                id=101,
                web_url=f"{change.web_url}#note-101",
                body=kwargs["body"],
                author_username="bot",
            )
            comments.append(note)
            return note

        def update_comment(**kwargs) -> ReviewComment:
            assert kwargs["note_id"] == comments[0].id
            note = comments[0].model_copy(update={"body": kwargs["body"]})
            comments[0] = note
            return note

        client.create_change_request_comment.side_effect = create_comment
        client.update_change_request_comment.side_effect = update_comment
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
    lookup = (
        Mock(return_value=None)
        if mode == "publish"
        else Mock(side_effect=AssertionError("Verified context lookup must not run"))
    )
    runner = ReviewRunner(
        repo_root=tmp_path,
        config=config,
        review_client=client,
        review_state_service=state_service,
        continuity_context_service=ReviewContinuityContextService(
            review_client=client,
            review_state_service=state_service,
            logger=LOGGER,
        ),
        projection_repair_service=ReviewProjectionRepairService(
            repo_root=tmp_path,
            config=config,
            review_state_service=state_service,
            review_projection_factory=lambda: None,
            logger=LOGGER,
        ),
        review_projection_factory=lambda: None,
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

    if mode == "publish":
        lookup.assert_called_once_with("org/repo", 9)
    else:
        lookup.assert_not_called()
    expected = {
        "dry_run": RunStatus.REVIEWED,
        "same_sha": RunStatus.REVIEWED,
        "context_failure": RunStatus.FAILED,
        "no_selection": RunStatus.NO_ISSUE,
        "publish": RunStatus.REVIEWED,
    }
    assert summary.status == expected[mode]
    if mode == "context_failure":
        assert state_service.state.runs[-1].failure.stage == FailureStage.REVIEW_CONTEXT
    if mode == "same_sha":
        assert "No new changes after the last review" in summary.message
    if mode == "publish":
        client.create_change_request_comment.assert_called_once()
        assert client.update_change_request_comment.called
        client.get_change_request_state.assert_called_with(
            repository_id="org/repo", change_request_number=9
        )
        assert len(comments) == 1
        envelope = decode_overview(comments[0].body)
        assert envelope is not None
        assert envelope.platform == platform
        assert envelope.repository_id == "org/repo"
        assert envelope.change_request_number == 9
        assert envelope.complete_passes[0].head_sha == "current"
        assert envelope.complete_passes[0].artifact.classification == "no_findings"
        assert state_service.state.reviews["9:current"].review_pass_id == (
            envelope.complete_passes[0].pass_id
        )
        assert "could not be synchronized" not in summary.message
    else:
        client.create_change_request_comment.assert_not_called()
        client.update_change_request_comment.assert_not_called()
    client.create_change_request_inline_comment.assert_not_called()
