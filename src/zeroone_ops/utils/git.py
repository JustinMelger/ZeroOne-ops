"""Git-related helpers."""

from pathlib import PurePosixPath


def sanitize_branch_fragment(value: str) -> str:
    """Convert text into a safe branch name fragment.

    Args:
        value: Raw text to sanitize.

    Returns:
        Lowercase hyphenated text safe to embed in branch names.
    """
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in cleaned.split("-") if part)


def build_remediation_branch_key(*, source: str, source_reference: str) -> str:
    """Return the stable source-aware key used in remediation branch names."""
    if source == "sonarqube":
        return source_reference
    return f"{source}-{source_reference}"


def build_issue_branch_name(*, branch_prefix: str, issue_key: str, file_path: str) -> str:
    """Build a predictable branch name for a selected issue.

    Args:
        branch_prefix: Configured branch prefix.
        issue_key: Stable finding key from the normalized work item.
        file_path: Repository-relative target file path.

    Returns:
        Safe git branch name.
    """
    path_name = PurePosixPath(file_path).stem
    return "/".join(
        part
        for part in [
            sanitize_branch_fragment(branch_prefix),
            sanitize_branch_fragment(issue_key),
            sanitize_branch_fragment(path_name),
        ]
        if part
    )
