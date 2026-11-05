"""Protect reference precedence, cached authors, and prior-context failure boundaries."""

import json
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from zeroone_ops.models.review import (
    ChangeRequestDiffRefs,
    ChangeRequestReviewCandidate,
    PriorReviewInlineComment,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    ReviewComment,
    ReviewInlineCommentDecision,
)
from zeroone_ops.models.review_overview import ReviewOverviewEnvelope, ReviewOverviewPass
from zeroone_ops.models.state import AppState, ChangeRequestReviewState, RepositoryState
from zeroone_ops.providers.review.platform import ReviewPlatformClientError
from zeroone_ops.services.review.continuity.review_continuity_context_service import (
    ReviewContinuityContextService,
)
from zeroone_ops.services.review.publish.review_overview_codec import (
    ReviewOverviewAuthorityError,
    ReviewOverviewError,
    encode_overview,
)
from zeroone_ops.services.review.publish.review_overview_coordinator import (
    ReviewOverviewCoordinator,
)
from zeroone_ops.services.review.state.review_state_service import ReviewStateService
from zeroone_ops.services.shared.state_store import StateStore


def _note(number: int, sha: str = "head", author: str = "bot") -> ReviewComment:
    payload = {
        "schema": "ai-sonar-bot/review-note/v1",
        "reviewed_change_request_number": 9,
        "reviewed_head_sha": sha,
        "classification": "no_findings",
        "summary": str(number),
        "findings_count": 0,
        "findings": [],
    }
    return ReviewComment(
        id=number,
        body="<!-- ai-sonar-bot:review-note:v1\n" + json.dumps(payload) + "\n-->",
        author_username=author,
        created_at="2026-01-01T00:00:00Z",
    )


def _change() -> ChangeRequestReviewCandidate:
    return ChangeRequestReviewCandidate(
        change_request_number=9,
        head_sha="head",
        title="Review",
        source_branch="fix",
        target_branch="main",
        web_url="https://example/pr/9",
    )


@pytest.mark.parametrize("author_failure", [False, True])
@pytest.mark.parametrize("fallback", [False, True])
def test_same_sha_then_prior_lookup_share_author_cache_without_sharing_reads(
    author_failure, fallback
):
    client = Mock()
    client.get_current_user_username.return_value = "bot"
    if author_failure:
        client.get_current_user_username.side_effect = RuntimeError("Unknown user")
    client.allows_machine_safe_comment_fallback.return_value = fallback
    client.list_change_request_comments.return_value = [
        _note(1),
        _note(3),
        _note(99, author="human"),
        _note(2, sha="earlier"),
    ]
    service = ReviewContinuityContextService(
        review_client=client,
        review_state_service=SimpleNamespace(state=SimpleNamespace(reviews={})),
        logger=logging.getLogger("review-test"),
    )
    assert not client.mock_calls

    reference = service.load_same_sha_review_reference(
        run_id="run",
        repository_id="org/repo",
        change_request=_change(),
    )
    prior = service.load_prior_review_context(
        run_id="run",
        repository_id="org/repo",
        change_request_number=9,
        current_head_sha="head",
    )

    if author_failure and not fallback:
        assert reference is None
    else:
        assert reference.note_id == (99 if author_failure else 3)
    assert prior.passes[0].note_id == 2
    client.get_current_user_username.assert_called_once_with()
    assert client.list_change_request_comments.call_count == 2


def test_authoritative_local_state_precedes_all_provider_calls():
    client = Mock(side_effect=AssertionError("No transport expected"))
    state = ChangeRequestReviewState(
        change_request_number=9,
        head_sha="head",
        status="manual_review_only",
        last_run_id="prior",
        summary="Stored authority",
        findings_count=0,
    )
    service = ReviewContinuityContextService(
        review_client=client,
        review_state_service=SimpleNamespace(state=SimpleNamespace(reviews={"9:head": state})),
        logger=logging.getLogger("review-test"),
    )
    result = service.load_same_sha_review_reference(
        run_id="run",
        repository_id="org/repo",
        change_request=_change(),
    )
    assert result.classification == "manual_review_only"
    assert result.summary == "Stored authority"
    assert not client.mock_calls


@pytest.mark.parametrize(
    "error_type", [ReviewPlatformClientError, httpx.HTTPError, OSError, RuntimeError]
)
def test_same_sha_lookup_preserves_exact_exception_boundary(error_type, caplog):
    client = Mock()
    client.list_change_request_comments.side_effect = error_type("Unavailable")
    service = ReviewContinuityContextService(
        review_client=client,
        review_state_service=SimpleNamespace(state=SimpleNamespace(reviews={})),
        logger=logging.getLogger("review-test"),
    )
    if error_type is RuntimeError:
        with pytest.raises(RuntimeError, match="Unavailable"):
            service.load_same_sha_review_reference(
                run_id="run", repository_id="org/repo", change_request=_change()
            )
        return
    assert (
        service.load_same_sha_review_reference(
            run_id="run", repository_id="org/repo", change_request=_change()
        )
        is None
    )
    assert len(caplog.records) == 1
    assert (
        caplog.records[0].getMessage()
        == "review same-sha lookup via provider comment failed; continuing without reuse"
    )
    client.get_current_user_username.assert_not_called()


@pytest.mark.parametrize(
    "mode", ["loader_error", "parser_error", "malformed", "wrong_request", "injected"]
)
def test_injected_prior_dependencies_and_failures_preserve_continuation(mode, caplog):
    client = Mock()
    loader = Mock()
    note = _note(3, sha="earlier")
    if mode == "wrong_request":
        note.body = note.body.replace(
            '"reviewed_change_request_number": 9', '"reviewed_change_request_number": 10'
        )
    loader.select_latest_prior_review_note.return_value = SimpleNamespace(
        selected_note=note,
        reason_code="selected",
        considered_note_count=1,
        author_matched_note_count=1,
        machine_safe_note_count=1,
        parseable_note_count=1,
        current_sha_skipped_count=0,
    )
    parser = None
    if mode == "loader_error":
        loader.select_latest_prior_review_note.side_effect = RuntimeError("Unavailable")
    if mode == "parser_error":
        parser = Mock()
        parser.parse_note.side_effect = RuntimeError("Bad parser")
    if mode == "malformed":
        note.body = "not a review"
    service = ReviewContinuityContextService(
        review_client=client,
        review_state_service=Mock(),
        logger=logging.getLogger("review-test"),
        prior_context_service=loader,
        prior_note_parser=parser,
    )

    result = service.load_prior_review_context(
        run_id="run",
        repository_id="org/repo",
        change_request_number=9,
        current_head_sha="head",
    )

    assert not client.mock_calls
    if mode == "injected":
        assert result.passes[0].reviewed_head_sha == "earlier"
    else:
        assert result is None
        assert len(caplog.records) == 1


def _overview_pass(sha="head", sequence=2):
    return ReviewOverviewPass(
        pass_id=f"pass-{sequence}",
        run_id="remote-run",
        head_sha=sha,
        sequence=sequence,
        completed_at=datetime(2026, 1, 1, tzinfo=UTC),
        diff_refs=ChangeRequestDiffRefs(base_sha="base", start_sha="start", head_sha=sha),
        inline_decisions=[
            ReviewInlineCommentDecision(
                finding_identity="stable-finding",
                severity="high",
                file_path="src/example.py",
                inline_comments_enabled=True,
                location_trust="trusted",
                existing_inline_comment_found=False,
                anchor_reuse_decision="new",
                anchor_reuse_reason="New finding",
                new_comment_id="inline-77",
            )
        ],
        artifact=PublishableReviewArtifact(
            classification="findings_present",
            summary="Provider authority",
            findings=[
                PublishableReviewFinding(
                    stable_identity="stable-finding",
                    severity="high",
                    file_path="src/example.py",
                    title="Regression",
                    evidence="Diff evidence",
                    explanation="Broken behavior",
                    suggested_follow_up="Repair behavior",
                    inline_comment=PriorReviewInlineComment(
                        comment_id="inline-77",
                        status="published",
                        anchor_file_path="src/example.py",
                        anchor_line_start=4,
                    ),
                )
            ],
        ),
        projection_pending=True,
        projection_warning="Retry me",
        projection_reference="logical-reference",
    )


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("max_prior", [0, 2])
def test_verified_overview_wins_and_hydrates_only_outside_dry_run(tmp_path, dry_run, max_prior):
    snapshot = _overview_pass()
    overview = ReviewOverviewEnvelope(
        platform="github",
        repository_id="org/repo",
        change_request_number=9,
        complete_passes=[snapshot],
        history=[snapshot.summary()],
    )
    coordinator = Mock()
    coordinator.discover.return_value = (ReviewComment(id=77, web_url="https://note"), overview)
    store = StateStore(
        tmp_path / "state.json",
        base_branch="main",
        gitlab_project_id=None,
        sonarqube_project_key=None,
    )
    state_service = ReviewStateService(
        state_store=store,
        state=AppState(repository=RepositoryState(base_branch="main")),
        max_prior_review_passes=max_prior,
    )
    state_service.state.reviews["9:head"] = ChangeRequestReviewState(
        change_request_number=9, head_sha="head", status="no_findings", last_run_id="stale"
    )
    before = state_service.state.model_dump_json()
    client = Mock()
    service = ReviewContinuityContextService(
        review_client=client,
        review_state_service=state_service,
        logger=logging.getLogger("review-test"),
        overview_coordinator=coordinator,
    )
    result = service.load_same_sha_review_reference(
        run_id="run", repository_id="org/repo", change_request=_change(), active_dry_run=dry_run
    )
    assert result.classification == "findings_present"
    assert result.findings[0].identity == "stable-finding"
    assert result.findings[0].inline_comment.comment_id == "inline-77"
    assert not client.mock_calls
    if dry_run:
        assert state_service.state.model_dump_json() == before
        assert not store.path.exists()
    else:
        hydrated = store.load().reviews["9:head"]
        assert hydrated.projection_artifact == snapshot.artifact
        assert hydrated.projection_retry_pending
        assert hydrated.projection_retry_warning == "Retry me"
        assert hydrated.review_pass_id == snapshot.pass_id
        assert hydrated.projection_reference == "logical-reference"
        assert hydrated.note_id == 77
        assert hydrated.overview_pass == snapshot
        assert hydrated.overview_pass is not snapshot


@pytest.mark.parametrize("max_prior", [0, 1, 5])
def test_prior_overview_context_uses_complete_snapshots_only_and_respects_bound(
    tmp_path, max_prior
):
    snapshots = [_overview_pass("earlier", 3), _overview_pass("older", 2)]
    summary_only = _overview_pass("summary-only", 1).summary()
    coordinator = Mock()
    coordinator.discover.return_value = (
        ReviewComment(id=77),
        ReviewOverviewEnvelope(
            platform="github",
            repository_id="org/repo",
            change_request_number=9,
            complete_passes=snapshots,
            history=[snapshot.summary() for snapshot in snapshots] + [summary_only],
        ),
    )
    state_service = _state_service(tmp_path)
    state_service.max_prior_review_passes = max_prior
    service = ReviewContinuityContextService(
        review_client=Mock(),
        review_state_service=state_service,
        logger=logging.getLogger("review-test"),
        overview_coordinator=coordinator,
    )
    result = service.load_prior_review_context(
        run_id="run", repository_id="org/repo", change_request_number=9, current_head_sha="head"
    )
    if max_prior == 0:
        assert result is None
        return
    assert [snapshot.reviewed_head_sha for snapshot in result.passes] == ["earlier", "older"][
        :max_prior
    ]
    assert result.passes[0].findings[0].identity == "stable-finding"


def test_overview_read_errors_do_not_fall_back_to_local_cache():
    coordinator = Mock()
    coordinator.discover.side_effect = RuntimeError("Overview read failed")
    service = ReviewContinuityContextService(
        review_client=Mock(),
        review_state_service=Mock(),
        logger=logging.getLogger("review-test"),
        overview_coordinator=coordinator,
    )
    with pytest.raises(RuntimeError, match="Overview read failed"):
        service.load_same_sha_review_reference(
            run_id="run", repository_id="org/repo", change_request=_change()
        )


def _state_service(tmp_path):
    return ReviewStateService(
        state_store=StateStore(
            tmp_path / "state.json",
            base_branch="main",
            gitlab_project_id=None,
            sonarqube_project_key=None,
        ),
        state=AppState(repository=RepositoryState(base_branch="main")),
    )


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("complete", [False, True])
def test_confirmed_deleted_overview_restores_only_complete_snapshot(tmp_path, dry_run, complete):
    snapshot = _overview_pass().model_copy(update={"projection_pending": False})
    state_service = _state_service(tmp_path)
    state_service.hydrate_overview_pass(
        change_request_number=9, review_pass=snapshot, note=ReviewComment(id=10, web_url="old")
    )
    if not complete:
        state_service.state.reviews["9:head"].overview_pass = None
    before = state_service.state.model_dump_json()
    coordinator = Mock()
    coordinator.discover.return_value = (None, None)
    restored = snapshot.model_copy(update={"projection_pending": True})
    coordinator.restore.return_value = (
        ReviewComment(id=99, web_url="new"),
        ReviewOverviewEnvelope(
            platform="github",
            repository_id="org/repo",
            change_request_number=9,
            complete_passes=[restored],
            history=[restored.summary()],
        ),
    )
    service = ReviewContinuityContextService(
        review_client=Mock(),
        review_state_service=state_service,
        logger=logging.getLogger("review-test"),
        overview_coordinator=coordinator,
    )
    reference = service.load_same_sha_review_reference(
        run_id="rerun", repository_id="org/repo", change_request=_change(), active_dry_run=dry_run
    )
    assert reference.classification == snapshot.artifact.classification
    if complete and not dry_run:
        coordinator.restore.assert_called_once_with(
            repository_id="org/repo",
            change_request_number=9,
            review_pass=restored,
            earlier_findings=state_service.state.reviews["9:head"].earlier_findings,
        )
        recovered = state_service.state_store.load().reviews["9:head"]
        assert recovered.note_id == 99
        assert recovered.note_url == "new"
        assert recovered.projection_retry_pending
        assert recovered.overview_pass == restored
        assert recovered.review_pass_id == snapshot.pass_id
        assert recovered.projection_reference == snapshot.projection_reference
        assert reference.findings[0].inline_comment.comment_id == "inline-77"
    else:
        coordinator.restore.assert_not_called()
        assert state_service.state.model_dump_json() == before


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("changed", ["none", "pass", "meaning", "remote_receipt"])
@pytest.mark.parametrize("receipt_kind", ["new", "reuse"])
def test_provider_authority_retains_only_matching_missing_actual_receipts(
    tmp_path, pending, changed, receipt_kind
):
    local = _overview_pass()
    if receipt_kind == "reuse":
        local.inline_decisions[0].new_comment_id = None
        local.inline_decisions[0].existing_comment_id = "inline-77"
        local.inline_decisions[0].anchor_reuse_decision = "reuse"
        local.inline_decisions[0].existing_inline_comment_found = True
    state_service = _state_service(tmp_path)
    state_service.hydrate_overview_pass(
        change_request_number=9, review_pass=local, note=ReviewComment(id=10)
    )
    remote = local.model_copy(
        deep=True,
        update={
            "projection_pending": pending,
            "projection_warning": "Provider warning",
            "projection_reference": "provider-logical-reference",
        },
    )
    remote.artifact.findings[0].inline_comment = None
    remote.inline_decisions.clear()
    if changed == "pass":
        remote = remote.model_copy(update={"pass_id": "other-pass"})
    if changed == "meaning":
        remote.artifact.findings[0].explanation = "Different finalized meaning"
    if changed == "remote_receipt":
        remote.artifact.findings[0].inline_comment = PriorReviewInlineComment(
            comment_id="remote-receipt", status="published", anchor_file_path="src/example.py"
        )
    coordinator = Mock()
    coordinator.discover.return_value = (
        ReviewComment(id=77),
        ReviewOverviewEnvelope(
            platform="github",
            repository_id="org/repo",
            change_request_number=9,
            complete_passes=[remote],
            history=[remote.summary()],
        ),
    )
    service = ReviewContinuityContextService(
        review_client=Mock(),
        review_state_service=state_service,
        logger=logging.getLogger("review-test"),
        overview_coordinator=coordinator,
    )
    result = service.load_same_sha_review_reference(
        run_id="rerun", repository_id="org/repo", change_request=_change()
    )
    receipt = result.findings[0].inline_comment
    if changed == "none":
        assert receipt.comment_id == "inline-77"
    elif changed == "remote_receipt":
        assert receipt.comment_id == "remote-receipt"
    else:
        assert receipt is None
    hydrated = state_service.state_store.load().reviews["9:head"]
    assert hydrated.projection_retry_pending is pending
    assert hydrated.projection_retry_warning == "Provider warning"
    assert hydrated.projection_reference == "provider-logical-reference"
    assert hydrated.overview_pass.artifact.findings[0].inline_comment == receipt
    if changed == "none":
        assert hydrated.overview_pass.inline_decisions == local.inline_decisions
    else:
        assert hydrated.overview_pass.inline_decisions == []
    assert local.artifact.findings[0].inline_comment.comment_id == "inline-77"


@pytest.mark.parametrize("error_type", [ReviewOverviewError, ReviewPlatformClientError, OSError])
@pytest.mark.parametrize("reference", ["local", "legacy", "none"])
def test_expected_discovery_failure_allows_only_existing_read_only_reuse(
    tmp_path, error_type, reference, caplog
):
    state_service = _state_service(tmp_path)
    if reference == "local":
        state_service.hydrate_overview_pass(
            change_request_number=9,
            review_pass=_overview_pass().model_copy(update={"projection_pending": False}),
            note=ReviewComment(id=10),
        )
    before = state_service.state.model_dump_json()
    client = Mock()
    client.get_current_user_username.side_effect = ReviewPlatformClientError("Author unavailable")
    client.allows_machine_safe_comment_fallback.return_value = True
    client.list_change_request_comments.return_value = [_note(3)] if reference == "legacy" else []
    coordinator = Mock()
    coordinator.discover.side_effect = error_type("Discovery failed")
    service = ReviewContinuityContextService(
        review_client=client,
        review_state_service=state_service,
        logger=logging.getLogger("review-test"),
        overview_coordinator=coordinator,
    )
    if reference == "none":
        with pytest.raises(error_type, match="Discovery failed"):
            service.load_same_sha_review_reference(
                run_id="rerun", repository_id="org/repo", change_request=_change()
            )
    else:
        result = service.load_same_sha_review_reference(
            run_id="rerun", repository_id="org/repo", change_request=_change()
        )
        if reference == "legacy":
            assert result.note_id == 3
        else:
            assert result.classification == "findings_present"
    coordinator.restore.assert_not_called()
    assert state_service.state.model_dump_json() == before
    assert any("read-only legacy reuse" in record.message for record in caplog.records)


@pytest.mark.parametrize("lookup", ["same_sha", "prior"])
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("conflict", ["duplicate", "malformed", "wrong_scope"])
def test_conflicting_authority_never_falls_back_to_cache_or_legacy(
    tmp_path, lookup, cached, conflict
):
    state_service = _state_service(tmp_path)
    snapshot = _overview_pass()
    if cached:
        state_service.hydrate_overview_pass(
            change_request_number=9, review_pass=snapshot, note=ReviewComment(id=10)
        )
    before = state_service.state.model_dump_json()
    envelope = ReviewOverviewEnvelope(
        platform="github",
        repository_id="elsewhere/repo" if conflict == "wrong_scope" else "org/repo",
        change_request_number=9,
        complete_passes=[snapshot],
        history=[snapshot.summary()],
    )
    body = encode_overview(envelope)
    if conflict == "malformed":
        body = "<!-- zeroone:review-overview:v1\ninvalid -->"
    client = Mock()
    client.get_current_user_username.return_value = "bot"
    comments = [ReviewComment(id=20, author_username="bot", body=body), _note(3)]
    if conflict == "duplicate":
        comments.append(ReviewComment(id=21, author_username="bot", body=body))
    client.list_change_request_comments.return_value = comments
    service = ReviewContinuityContextService(
        review_client=client,
        review_state_service=state_service,
        logger=logging.getLogger("review-test"),
        overview_coordinator=ReviewOverviewCoordinator(client, "github"),
    )

    with pytest.raises(ReviewOverviewAuthorityError):
        if lookup == "same_sha":
            service.load_same_sha_review_reference(
                run_id="rerun", repository_id="org/repo", change_request=_change()
            )
        else:
            service.load_prior_review_context(
                run_id="rerun",
                repository_id="org/repo",
                change_request_number=9,
                current_head_sha="next-head",
            )

    assert state_service.state.model_dump_json() == before
    client.create_change_request_comment.assert_not_called()
    client.update_change_request_comment.assert_not_called()
    assert client.list_change_request_comments.call_count == 1


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize(
    "error_type", [ReviewOverviewError, ReviewPlatformClientError, httpx.ReadTimeout, OSError]
)
def test_unavailable_discovery_withholds_pending_repair_but_allows_dry_run(
    tmp_path, dry_run, error_type
):
    state_service = _state_service(tmp_path)
    state_service.hydrate_overview_pass(
        change_request_number=9,
        review_pass=_overview_pass().model_copy(update={"projection_pending": True}),
        note=ReviewComment(id=10),
    )
    before = state_service.state.model_dump_json()
    coordinator = Mock()
    coordinator.discover.side_effect = error_type("Discovery unavailable")
    service = ReviewContinuityContextService(
        review_client=Mock(),
        review_state_service=state_service,
        logger=logging.getLogger("review-test"),
        overview_coordinator=coordinator,
    )

    if dry_run:
        reference = service.load_same_sha_review_reference(
            run_id="rerun",
            repository_id="org/repo",
            change_request=_change(),
            active_dry_run=True,
        )
        assert reference.classification == "findings_present"
    else:
        with pytest.raises(ReviewOverviewError, match="repair withheld"):
            service.load_same_sha_review_reference(
                run_id="rerun", repository_id="org/repo", change_request=_change()
            )

    assert state_service.state.model_dump_json() == before
    coordinator.restore.assert_not_called()
