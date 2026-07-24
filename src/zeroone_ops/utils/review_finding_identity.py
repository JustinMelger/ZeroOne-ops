"""Canonical identity helpers for review finding continuity."""

from __future__ import annotations

import re
from typing import Protocol

from zeroone_ops.utils.finding_identity import (
    normalize_identity_structured_field,
    normalize_identity_text,
)


class SupportsReviewFindingIdentity(Protocol):
    """Represent the bounded finding fields needed for canonical identity building."""

    file_path: str
    title: str
    issue_kind: str | None
    symbol: str | None
    region_hint: str | None


def build_review_finding_identity(finding: SupportsReviewFindingIdentity) -> str:
    """Build a canonical machine-facing identity for one review finding."""
    normalized_path = re.sub(r"\s+", "", finding.file_path.strip().lower())
    subject_parts = [
        normalize_identity_structured_field(finding.issue_kind),
        normalize_identity_structured_field(finding.symbol),
        normalize_identity_structured_field(finding.region_hint),
    ]
    normalized_subject = "::".join(part for part in subject_parts if part)
    if not normalized_subject:
        normalized_subject = _normalize_title_subject(finding.title)
    return f"{normalized_path}::{normalized_subject}"


def build_legacy_review_finding_identity(finding: SupportsReviewFindingIdentity) -> str:
    """Build the legacy title-derived identity for compatibility matching."""
    normalized_path = re.sub(r"\s+", "", finding.file_path.strip().lower())
    return f"{normalized_path}::{_normalize_title_subject(finding.title)}"


def _normalize_title_subject(title: str) -> str:
    """Normalize a finding title into a conservative subject key."""
    return normalize_identity_text(title)
