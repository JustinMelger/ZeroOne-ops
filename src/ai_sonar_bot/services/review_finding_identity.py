"""Canonical identity helpers for review finding continuity."""

from __future__ import annotations

import re

from ai_sonar_bot.models.review import ReviewFinding

_IDENTITY_STOP_TOKENS = frozenset({"always", "make"})
_IDENTITY_TOKEN_ALIASES = {
    "breaks": "fail",
    "break": "fail",
    "broken": "fail",
    "fails": "fail",
    "failing": "fail",
    "failure": "fail",
    "fail": "fail",
    "makes": "make",
    "make": "make",
    "lookup": "lookup",
    "retrieval": "lookup",
    "retrieve": "lookup",
    "details": "detail",
}


def build_review_finding_identity(finding: ReviewFinding) -> str:
    """Build a canonical machine-facing identity for one review finding."""
    normalized_path = re.sub(r"\s+", "", finding.file_path.strip().lower())
    subject_parts = [
        _normalize_structured_field(finding.issue_kind),
        _normalize_structured_field(finding.symbol),
        _normalize_structured_field(finding.region_hint),
    ]
    normalized_subject = "::".join(part for part in subject_parts if part)
    if not normalized_subject:
        normalized_subject = _normalize_title_subject(finding.title)
    return f"{normalized_path}::{normalized_subject}"


def build_legacy_review_finding_identity(finding: ReviewFinding) -> str:
    """Build the legacy title-derived identity for compatibility matching."""
    normalized_path = re.sub(r"\s+", "", finding.file_path.strip().lower())
    return f"{normalized_path}::{_normalize_title_subject(finding.title)}"


def _normalize_title_subject(title: str) -> str:
    """Normalize a finding title into a conservative subject key."""
    subject_tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9_]+", title.lower()):
        normalized_token = _normalize_title_token(token)
        normalized_token = _IDENTITY_TOKEN_ALIASES.get(normalized_token, normalized_token)
        if normalized_token in _IDENTITY_STOP_TOKENS:
            continue
        if len(normalized_token) >= 4:
            subject_tokens.add(normalized_token)
    if not subject_tokens:
        return "unknown"
    return "-".join(sorted(subject_tokens))


def _normalize_title_token(token: str) -> str:
    """Lightly normalize title tokens while preserving current canonical keys."""
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("ion") and len(token) > 5:
        return token[:-3]
    return token


def _normalize_structured_field(value: str | None) -> str | None:
    """Normalize one structured continuity field for identity use."""
    if value is None:
        return None
    normalized = re.sub(r"[^a-z0-9_]+", "-", value.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or None
