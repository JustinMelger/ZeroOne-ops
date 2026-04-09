"""Fixture helpers for LLM-backed workflows."""

from __future__ import annotations

import json
from pathlib import Path

from ai_sonar_bot.models.analysis import IssueAnalysis, StructuredEditProposal
from ai_sonar_bot.models.review import ReviewResult


class LLMFixtureError(RuntimeError):
    """Raised when an LLM fixture file is missing or invalid."""


def load_analysis_fixture(path: Path) -> IssueAnalysis:
    """Load an issue analysis result from a JSON fixture."""
    payload = _load_fixture_payload(path, fixture_kind="analysis")
    try:
        return IssueAnalysis.model_validate(payload)
    except Exception as error:
        raise LLMFixtureError("Invalid LLM analysis fixture structure.") from error


def load_structured_edit_fixture(path: Path) -> StructuredEditProposal:
    """Load a structured edit proposal from a JSON fixture."""
    payload = _load_fixture_payload(path, fixture_kind="structured edit")
    try:
        return StructuredEditProposal.model_validate(payload)
    except Exception as error:
        raise LLMFixtureError("Invalid LLM structured edit fixture structure.") from error


def load_review_fixture(path: Path) -> ReviewResult:
    """Load a structured review result from a JSON fixture."""
    payload = _load_fixture_payload(path, fixture_kind="review")
    try:
        return ReviewResult.model_validate(payload)
    except Exception as error:
        raise LLMFixtureError("Invalid LLM review fixture structure.") from error


def _load_fixture_payload(path: Path, *, fixture_kind: str) -> dict[str, object]:
    """Load and validate a raw JSON fixture payload."""
    if not path.exists():
        raise LLMFixtureError(f"LLM {fixture_kind} fixture file not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LLMFixtureError(f"LLM {fixture_kind} fixture file is invalid JSON: {path}") from error

    if not isinstance(payload, dict):
        raise LLMFixtureError(f"Unexpected LLM {fixture_kind} fixture payload.")
    return payload
