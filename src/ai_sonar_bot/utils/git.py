"""Git-related helpers."""


def sanitize_branch_fragment(value: str) -> str:
    """Convert text into a safe branch name fragment.

    Args:
        value: Raw text to sanitize.

    Returns:
        Lowercase hyphenated text safe to embed in branch names.
    """
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in cleaned.split("-") if part)
