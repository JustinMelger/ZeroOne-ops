"""Enforce an application budget without truncating authoritative evidence."""

BATCH_PAYLOAD_MAX_BYTES = 60_000


class ProjectionSizeExceeded(RuntimeError):
    """A complete batch projection cannot safely be sent to a provider."""


def validate_batch_payload(payload: str) -> str:
    """Return unchanged content or reject it before any provider transport."""
    if len(payload.encode("utf-8")) > BATCH_PAYLOAD_MAX_BYTES:
        raise ProjectionSizeExceeded("Batch projection exceeds the 60,000-byte application budget.")
    return payload
