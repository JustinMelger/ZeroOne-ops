"""Code context builder.

This module reads repository files and prepares contextual source text for the
LLM prompt.
"""

from __future__ import annotations

from pathlib import Path

from ai_sonar_bot.models.analysis import CodeContextSnippet, IssueContext
from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.remediation import RemediationExecutionTarget


class ContextBuilder:
    """Build prompt context for one execution target.

    Args:
        repo_root: Repository root path.
        config: Loaded application configuration.
    """

    def __init__(self, repo_root: Path, config: AppConfig) -> None:
        """Initialize the context builder.

        Args:
            repo_root: Repository root path.
            config: Loaded application configuration.
        """
        self.repo_root = repo_root
        self.config = config

    def build(self, target: RemediationExecutionTarget) -> IssueContext | None:
        """Build code context for one execution target.

        Args:
            target: Remediation target to analyze.

        Returns:
            Structured source context for the issue, or ``None`` if the file is
            missing.
        """
        return build_issue_context(
            repo_root=self.repo_root,
            config=self.config,
            issue_key=target.source_ref,
            file_path=target.file_path,
            issue_line=target.line,
        )


def build_issue_context(
    *,
    repo_root: Path,
    config: AppConfig,
    issue_key: str,
    file_path: str,
    issue_line: int | None,
) -> IssueContext | None:
    """Build code context for a repository-relative target file."""
    target = repo_root / file_path
    if not target.exists():
        return None

    file_size_bytes = target.stat().st_size
    raw_content = target.read_text(encoding="utf-8")
    lines = raw_content.splitlines()
    line_count = len(lines)
    clamped_issue_line = _clamp_issue_line(issue_line, line_count)

    if file_size_bytes <= config.analysis.max_file_bytes:
        start_line = 1
        end_line = line_count if line_count > 0 else 1
        snippet_lines = lines
        full_file_included = True
        truncated = False
    else:
        start_line, end_line = _window_bounds(
            issue_line=clamped_issue_line,
            line_count=line_count,
            lines_before=config.analysis.context_lines_before,
            lines_after=config.analysis.context_lines_after,
        )
        snippet_lines = lines[start_line - 1 : end_line]
        full_file_included = False
        truncated = True

    return IssueContext(
        issue_key=issue_key,
        file_path=file_path,
        line=issue_line,
        file_size_bytes=file_size_bytes,
        snippet=CodeContextSnippet(
            start_line=start_line,
            end_line=end_line,
            content=_format_with_line_numbers(start_line=start_line, lines=snippet_lines),
        ),
        full_file_included=full_file_included,
        truncated=truncated,
    )


def _clamp_issue_line(issue_line: int | None, line_count: int) -> int:
    """Clamp an issue line to the available file range.

    Args:
        issue_line: Reported SonarQube line number.
        line_count: Total line count in the file.

    Returns:
        A valid one-based line number for the file.
    """
    if line_count <= 0:
        return 1
    if issue_line is None:
        return 1
    return max(1, min(issue_line, line_count))


def _window_bounds(
    *,
    issue_line: int,
    line_count: int,
    lines_before: int,
    lines_after: int,
) -> tuple[int, int]:
    """Compute focused snippet bounds around an issue line.

    Args:
        issue_line: One-based issue line number.
        line_count: Total line count in the file.
        lines_before: Desired context lines before the issue.
        lines_after: Desired context lines after the issue.

    Returns:
        Inclusive one-based start and end line numbers.
    """
    start_line = max(1, issue_line - lines_before)
    end_line = min(line_count, issue_line + lines_after)
    if line_count == 0:
        return 1, 1
    return start_line, end_line


def _format_with_line_numbers(*, start_line: int, lines: list[str]) -> str:
    """Format lines with one-based line numbers.

    Args:
        start_line: First source line number in the snippet.
        lines: Source lines to format.

    Returns:
        Newline-delimited source with line-number prefixes.
    """
    if not lines:
        return ""
    return "\n".join(f"{index:>4}: {line}" for index, line in enumerate(lines, start=start_line))
