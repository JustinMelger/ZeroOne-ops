"""Historical payloads remain readable without obsolete Python accessors."""

from datetime import UTC, datetime

import pytest

from zeroone_ops.models.analysis import PatchProposal, StructuredEditProposal
from zeroone_ops.models.policy import (
    PolicyAction,
    PolicyActionParseResult,
    PolicyIssueClassStateEntry,
    PolicySeverityStateEntry,
)
from zeroone_ops.models.state import IssueState, RunRecord


@pytest.mark.parametrize("model", [PatchProposal, StructuredEditProposal])
def test_proposal_legacy_fields_decode_to_neutral_names(model) -> None:
    proposal = model.model_validate(
        {
            "issue_key": "finding",
            "commit_message": "chore: annotate helper",
            "mr_title": "chore: annotate helper",
            "mr_description": "Add the missing annotation.",
            **({"unified_diff": "diff"} if model is PatchProposal else {}),
        }
    )

    assert proposal.change_request_title == "chore: annotate helper"
    assert proposal.change_request_description == "Add the missing annotation."
    assert "mr_title" not in proposal.model_dump()
    assert "mr_description" not in proposal.model_dump()
    assert not hasattr(proposal, "mr_title")
    assert not hasattr(proposal, "mr_description")


@pytest.mark.parametrize("model", [IssueState, RunRecord])
def test_state_legacy_url_decodes_without_losing_linkage(model) -> None:
    state = model.model_validate(
        {
            "run_id": "run-1",
            "last_run_id": "run-1",
            "status": "selected",
            "started_at": datetime(2026, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
            "mr_url": "https://gitlab.example/project/-/merge_requests/1",
        }
    )

    assert state.change_request_url == "https://gitlab.example/project/-/merge_requests/1"
    assert "mr_url" not in state.model_dump()
    assert not hasattr(state, "mr_url")


@pytest.mark.parametrize(
    ("model", "fields"),
    [
        (PolicySeverityStateEntry, {"severity": "high", "enabled": True}),
        (
            PolicyIssueClassStateEntry,
            {"source": "ruff-sarif", "issue_key": "F401", "reason": "test"},
        ),
        (PolicyAction, {"action_type": "show_policy", "raw_command": "/zeroone policy show"}),
        (
            PolicyActionParseResult,
            {"matched_prefix": True, "accepted": False, "raw_command": "test"},
        ),
    ],
)
def test_policy_legacy_comment_id_remains_readable(model, fields) -> None:
    state = model.model_validate({**fields, "note_id": 42})

    assert state.comment_id == 42
    assert not hasattr(state, "note_id")
    if model in (PolicySeverityStateEntry, PolicyIssueClassStateEntry):
        assert state.model_dump(by_alias=True)["note_id"] == 42
