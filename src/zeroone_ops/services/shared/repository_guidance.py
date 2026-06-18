"""Shared bounded repository guidance discovery."""

from __future__ import annotations

import re
from pathlib import Path

from zeroone_ops.models.analysis import RepositoryGuidanceContext

GUIDANCE_HEADING_PATTERN = re.compile(r"^(#+)\s+.+$")
GUIDANCE_BULLET_PATTERN = re.compile(r"^([-*]|\d+\.)\s+.+$")
GUIDANCE_PATHS = (
    "AGENT.md",
    "docs/engineering-standards.md",
)
GUIDANCE_GLOBS = ("docs/technical-design*.md",)
MAX_GUIDANCE_FILES = 4
MAX_GUIDANCE_LINES = 16
MAX_GUIDANCE_CHARS = 1_200


def load_repository_guidance(repo_root: Path) -> list[RepositoryGuidanceContext]:
    """Load a few bounded repository guidance excerpts when available."""
    guidance_paths: list[Path] = []
    for relative_path in GUIDANCE_PATHS:
        target = repo_root / relative_path
        if target.exists() and target.is_file():
            guidance_paths.append(target)
    for pattern in GUIDANCE_GLOBS:
        for target in sorted(repo_root.glob(pattern)):
            if target.is_file() and target not in guidance_paths:
                guidance_paths.append(target)

    guidance_entries: list[RepositoryGuidanceContext] = []
    for target in guidance_paths[:MAX_GUIDANCE_FILES]:
        summary = _extract_guidance_summary(target)
        if summary is None:
            continue
        guidance_entries.append(
            RepositoryGuidanceContext(
                file_path=target.relative_to(repo_root).as_posix(),
                summary=summary,
            )
        )
    return guidance_entries


def _extract_guidance_summary(path: Path) -> str | None:
    """Return one bounded excerpt from a repository guidance file."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return None

    collected: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not (
            GUIDANCE_HEADING_PATTERN.match(line)
            or GUIDANCE_BULLET_PATTERN.match(line)
            or len(collected) < 3
        ):
            continue
        collected.append(line)
        summary = "\n".join(collected)
        if len(collected) >= MAX_GUIDANCE_LINES or len(summary) >= MAX_GUIDANCE_CHARS:
            break

    if not collected:
        return None

    summary = "\n".join(collected)
    if len(summary) > MAX_GUIDANCE_CHARS:
        return f"{summary[: MAX_GUIDANCE_CHARS - 3].rstrip()}..."
    return summary
