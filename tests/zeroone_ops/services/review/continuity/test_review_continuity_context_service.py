"""Protect reference precedence, cached authors, and prior-context failure boundaries."""

import json
import logging
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from zeroone_ops.models.review import ChangeRequestReviewCandidate, ReviewComment
from zeroone_ops.models.state import ChangeRequestReviewState
from zeroone_ops.providers.review.platform import ReviewPlatformClientError
from zeroone_ops.services.review.continuity.review_continuity_context_service import (
    ReviewContinuityContextService,
)


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
