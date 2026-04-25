"""Clock helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def now_utc() -> datetime:
    """Return the current UTC time.

    Returns:
        Current timezone-aware UTC datetime.
    """
    return datetime.now(UTC)
