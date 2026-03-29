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


def build_issue_branch_name(*, branch_prefix: str, issue_key: str, file_path: str) -> str:
    """Build a predictable branch name for a selected issue.

    Args:
        branch_prefix: Configured branch prefix.
        issue_key: SonarQube issue key.
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
