"""Encode bounded overview authority without allowing nested HTML delimiters."""

from __future__ import annotations

import json

from pydantic import ValidationError

from zeroone_ops.models.review_overview import ReviewOverviewEnvelope

OVERVIEW_START = "<!-- zeroone:review-overview:v1\n"
OVERVIEW_END = "\nzeroone:review-overview:end -->"
MAX_OVERVIEW_BYTES = 60_000


class ReviewOverviewError(ValueError):
    """Indicate that overview authority cannot safely be read or written."""


class ReviewOverviewAuthorityError(ReviewOverviewError):
    """Reject conflicting or malformed authority without falling back to cached evidence."""


def encode_overview(envelope: ReviewOverviewEnvelope) -> str:
    """Serialize complete evidence, escaping comment delimiters losslessly."""
    payload = json.dumps(
        envelope.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")
    )
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f"{OVERVIEW_START}{payload}{OVERVIEW_END}"


def decode_overview(body: str | None) -> ReviewOverviewEnvelope | None:
    """Decode one complete envelope or reject malformed managed authority."""
    text = body or ""
    if "zeroone:review-overview" not in text:
        return None
    if text.count(OVERVIEW_START) != 1 or text.count(OVERVIEW_END) != 1:
        raise ReviewOverviewAuthorityError(
            "Managed review overview markers are malformed or duplicated."
        )
    start = text.index(OVERVIEW_START) + len(OVERVIEW_START)
    end = text.index(OVERVIEW_END)
    if end < start or len(text.encode("utf-8")) > MAX_OVERVIEW_BYTES:
        raise ReviewOverviewAuthorityError(
            "Managed review overview is invalid or exceeds the payload budget."
        )
    try:
        return ReviewOverviewEnvelope.model_validate_json(text[start:end])
    except ValidationError as error:
        raise ReviewOverviewAuthorityError(
            "Managed review overview evidence is invalid."
        ) from error


def validate_overview_payload(body: str) -> str:
    """Reject oversized complete serialized bodies without truncating authority."""
    if len(body.encode("utf-8")) > MAX_OVERVIEW_BYTES:
        raise ReviewOverviewError("Review overview exceeds the 60,000-byte payload budget.")
    return body
