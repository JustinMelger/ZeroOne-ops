"""Git-related helpers."""

import hashlib
from pathlib import PurePosixPath

_MAX_BRANCH_PREFIX_LENGTH = 32
_MAX_BRANCH_IDENTITY_FRAGMENT_LENGTH = 72
_MAX_BRANCH_PATH_FRAGMENT_LENGTH = 32


def sanitize_branch_fragment(value: str) -> str:
    """Convert text into a safe branch name fragment.

    Args:
        value: Raw text to sanitize.

    Returns:
        Lowercase hyphenated text safe to embed in branch names.
    """
    cleaned = "".join(char.lower() if char.isascii() and char.isalnum() else "-" for char in value)
    return "-".join(part for part in cleaned.split("-") if part)


def build_remediation_branch_name(
    *,
    branch_prefix: str,
    source: str,
    source_reference: str,
    file_path: str,
) -> str:
    """Build an unambiguous branch name for a normalized remediation item."""
    path_name = PurePosixPath(file_path).stem
    return "/".join(
        part
        for part in [
            _truncate_branch_fragment(
                sanitize_branch_fragment(branch_prefix),
                maximum_length=_MAX_BRANCH_PREFIX_LENGTH,
            ),
            _branch_identity_fragment(source, fallback="source"),
            _branch_identity_fragment(source_reference, fallback="finding"),
            _truncate_branch_fragment(
                sanitize_branch_fragment(path_name),
                maximum_length=_MAX_BRANCH_PATH_FRAGMENT_LENGTH,
            ),
        ]
        if part
    )


def build_remediation_branch_lookup_names(
    *,
    branch_prefix: str,
    source: str,
    source_reference: str,
    file_path: str,
) -> tuple[str, ...]:
    """Return canonical and compatible legacy names for open-request lookup."""
    canonical_name = build_remediation_branch_name(
        branch_prefix=branch_prefix,
        source=source,
        source_reference=source_reference,
        file_path=file_path,
    )
    if source != "sonarqube":
        return (canonical_name,)
    legacy_name = build_issue_branch_name(
        branch_prefix=branch_prefix,
        issue_key=source_reference,
        file_path=file_path,
    )
    return (canonical_name,) if canonical_name == legacy_name else (canonical_name, legacy_name)


def _branch_identity_fragment(value: str, *, fallback: str) -> str:
    """Return a readable, collision-resistant branch segment for raw identity text."""
    fragment = sanitize_branch_fragment(value) or fallback
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    readable_length = _MAX_BRANCH_IDENTITY_FRAGMENT_LENGTH - len(digest) - 1
    return f"{_truncate_branch_fragment(fragment, maximum_length=readable_length)}-{digest}"


def _truncate_branch_fragment(value: str, *, maximum_length: int) -> str:
    """Keep a readable branch fragment within its fixed ref-name budget."""
    return value[:maximum_length]


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
