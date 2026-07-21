"""Intentional Ruff dogfooding sample for SARIF finding ingestion."""


def uses_boolean_equality(flag: bool) -> bool:
    """Return the input flag through an intentionally noisy comparison."""
    return flag == True
