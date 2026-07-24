"""Shared fallback identity helpers for normalized findings."""

from __future__ import annotations

import re

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


def build_fallback_finding_identity(
    *,
    repository_path: str,
    title: str,
    summary: str,
    category: str | None = None,
    diagnostic_code: str | None = None,
    region_hint: str | None = None,
) -> str:
    """Build a conservative shared fallback identity for one normalized finding."""
    normalized_path = re.sub(r"\s+", "", repository_path.strip().lower())
    subject_parts = [
        normalize_identity_structured_field(category),
        normalize_identity_structured_field(diagnostic_code),
        normalize_identity_structured_field(region_hint),
    ]
    normalized_subject = "::".join(part for part in subject_parts if part)
    if not normalized_subject:
        normalized_subject = normalize_identity_text(title)
    if normalized_subject == "unknown" and summary.strip():
        normalized_subject = normalize_identity_text(summary)
    return f"{normalized_path}::{normalized_subject}"


def normalize_identity_text(text: str) -> str:
    """Normalize bounded finding text into a conservative subject key."""
    subject_tokens: set[str] = set()
    for token in re.findall(r"[a-z0-9_]+", text.lower()):
        normalized_token = normalize_identity_token(token)
        normalized_token = _IDENTITY_TOKEN_ALIASES.get(normalized_token, normalized_token)
        if normalized_token in _IDENTITY_STOP_TOKENS:
            continue
        if len(normalized_token) >= 4:
            subject_tokens.add(normalized_token)
    if not subject_tokens:
        return "unknown"
    return "-".join(sorted(subject_tokens))


def normalize_identity_token(token: str) -> str:
    """Lightly normalize tokens while preserving stable identity keys."""
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("ion") and len(token) > 5:
        return token[:-3]
    return token


def normalize_identity_structured_field(value: str | None) -> str | None:
    """Normalize one structured field for shared identity use."""
    if value is None:
        return None
    normalized = re.sub(r"[^a-z0-9_]+", "-", value.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or None
