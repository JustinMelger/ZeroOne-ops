"""Intentional Ruff dogfooding sample for SARIF finding ingestion."""


def build_value() -> int:
    """Return a constant while keeping one unused local for Ruff output."""
    unused_value = 1
    return 2
