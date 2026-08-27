"""Shared bounded repository guidance discovery."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from markdown_it import MarkdownIt
from markdown_it.token import Token

from zeroone_ops.models.analysis import RepositoryGuidanceContext

LOGGER = logging.getLogger(__name__)

GUIDANCE_PATHS = (
    "AGENTS.md",
    "AGENT.md",
    "docs/engineering-standards.md",
)
GUIDANCE_GLOBS = ("docs/technical-design*.md",)
MAX_GUIDANCE_FILES = 4
MAX_GUIDANCE_LINES = 32
MAX_GUIDANCE_CHARS = 2_400
_SECTION_LINE_BUDGETS = (12, 10, 10)
_OPERATIONAL_HEADING_TERMS = ("command", "setup", "verification", "testing")
_GUIDANCE_HEADING_PRIORITIES = (
    (("rule",), 15),
    (("instruction",), 15),
    (("expectation",), 15),
    (("standard",), 15),
    (("convention",), 15),
    (("verification",), 15),
    (("review",), 10),
    (("testing",), 10),
    (("architecture",), 10),
    (("boundary",), 10),
)
_GUIDANCE_DIRECTIVE_PREFIXES = (
    "must ",
    "should ",
    "do not ",
    "never ",
    "always ",
    "prefer ",
    "keep ",
    "use ",
    "avoid ",
    "check ",
    "require ",
    "run ",
    "treat ",
)


@dataclass(frozen=True)
class _GuidanceSelection:
    """Represent one bounded guidance selection and its diagnostics."""

    summary: str | None
    selected_lines: int
    skipped_navigation_items: int
    line_truncated: bool
    character_truncated: bool


def load_repository_guidance(
    repo_root: Path,
    *,
    configured_paths: list[str] | None = None,
) -> list[RepositoryGuidanceContext]:
    """Load a few bounded repository guidance excerpts when available."""
    guidance_paths: list[Path] = []
    resolved_repo_root = repo_root.resolve()
    paths = GUIDANCE_PATHS if configured_paths is None else configured_paths
    for relative_path in paths:
        target = repo_root / relative_path
        _append_repository_guidance_path(guidance_paths, target, repo_root, resolved_repo_root)
    if configured_paths is None:
        for pattern in GUIDANCE_GLOBS:
            for target in sorted(repo_root.glob(pattern)):
                if target not in guidance_paths:
                    _append_repository_guidance_path(
                        guidance_paths,
                        target,
                        repo_root,
                        resolved_repo_root,
                    )

    guidance_entries: list[RepositoryGuidanceContext] = []
    for target in guidance_paths[:MAX_GUIDANCE_FILES]:
        try:
            selection = _extract_guidance_summary(target)
        except (OSError, UnicodeDecodeError) as error:
            LOGGER.warning(
                "skipped unreadable repository guidance [path=%s error_type=%s]",
                target.relative_to(repo_root).as_posix(),
                type(error).__name__,
            )
            continue
        if selection.summary is None:
            continue
        LOGGER.info(
            "repository guidance selected "
            "[path=%s selected_lines=%s skipped_navigation_items=%s "
            "line_truncated=%s character_truncated=%s]",
            target.relative_to(repo_root).as_posix(),
            selection.selected_lines,
            selection.skipped_navigation_items,
            selection.line_truncated,
            selection.character_truncated,
        )
        guidance_entries.append(
            RepositoryGuidanceContext(
                file_path=target.relative_to(repo_root).as_posix(),
                summary=selection.summary,
            )
        )
    return guidance_entries


def _append_repository_guidance_path(
    guidance_paths: list[Path],
    target: Path,
    repo_root: Path,
    resolved_repo_root: Path,
) -> None:
    """Append an existing regular guidance file contained by the repository."""
    if not target.exists() or not target.is_file():
        return
    try:
        target.resolve().relative_to(resolved_repo_root)
    except (OSError, ValueError):
        LOGGER.warning(
            "skipped repository guidance outside repository [path=%s]",
            target.relative_to(repo_root).as_posix(),
        )
        return
    guidance_paths.append(target)


def _extract_guidance_summary(path: Path) -> _GuidanceSelection:
    """Return one bounded Markdown-aware excerpt from a guidance file."""
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return _GuidanceSelection(None, 0, 0, False, False)

    lines = text.splitlines()
    tokens = MarkdownIt("commonmark", {"html": False}).parse(text)
    navigation_ranges = _navigation_list_item_ranges(tokens)
    blocks = _guidance_blocks(tokens, lines, navigation_ranges)

    selected_blocks: list[str] = []
    selected_lines = 0
    selected_chars = 0
    line_truncated = False
    character_truncated = False
    for block in blocks:
        block_lines = len(block.splitlines())
        block_chars = len(block)
        separator_lines = 1 if selected_blocks else 0
        separator_chars = 2 if selected_blocks else 0
        if selected_lines + separator_lines + block_lines <= MAX_GUIDANCE_LINES and (
            selected_chars + separator_chars + block_chars <= MAX_GUIDANCE_CHARS
        ):
            selected_blocks.append(block)
            selected_lines += separator_lines + block_lines
            selected_chars += separator_chars + block_chars
            continue

        if selected_blocks:
            line_truncated = selected_lines + separator_lines + block_lines > MAX_GUIDANCE_LINES
            character_truncated = (
                selected_chars + separator_chars + block_chars > MAX_GUIDANCE_CHARS
            )
            break

        truncated, truncated_by_lines, truncated_by_chars = _truncate_first_block(block)
        selected_blocks.append(truncated)
        selected_lines = len(truncated.splitlines())
        line_truncated = truncated_by_lines
        character_truncated = truncated_by_chars
        break

    if not selected_blocks:
        return _GuidanceSelection(None, 0, len(navigation_ranges), False, False)
    return _GuidanceSelection(
        "\n\n".join(selected_blocks),
        selected_lines,
        len(navigation_ranges),
        line_truncated,
        character_truncated,
    )


def _navigation_list_item_ranges(tokens: list[Token]) -> list[tuple[int, int]]:
    """Return source ranges for list items that only contain a Markdown link."""
    ranges: list[tuple[int, int]] = []
    for index, token in enumerate(tokens):
        if token.type != "list_item_open" or token.map is None:
            continue
        end_index = _matching_list_item_close(tokens, index)
        if end_index is None:
            continue
        inline_tokens = [
            candidate
            for candidate in tokens[index + 1 : end_index]
            if candidate.type == "inline" and candidate.children is not None
        ]
        if len(inline_tokens) == 1 and _is_link_only_inline(inline_tokens[0]):
            ranges.append((token.map[0], token.map[1]))
    return ranges


def _matching_list_item_close(tokens: list[Token], start_index: int) -> int | None:
    """Return the token index of the matching list-item close token."""
    depth = 0
    for index, token in enumerate(tokens[start_index:], start=start_index):
        if token.type == "list_item_open":
            depth += 1
        elif token.type == "list_item_close":
            depth -= 1
            if depth == 0:
                return index
    return None


def _is_link_only_inline(token: Token) -> bool:
    """Return whether inline content is exactly one link with optional whitespace."""
    children = token.children or []
    meaningful = [child for child in children if child.type != "text" or child.content.strip()]
    return (
        len(meaningful) == 3
        and meaningful[0].type == "link_open"
        and meaningful[1].type == "text"
        and meaningful[2].type == "link_close"
    )


def _guidance_blocks(
    tokens: list[Token],
    lines: list[str],
    navigation_ranges: list[tuple[int, int]],
) -> list[str]:
    """Select structurally prioritized Markdown blocks suitable for guidance context."""
    blocks: list[tuple[int, int, int, str]] = []
    selected_ranges: set[tuple[int, int]] = set()
    previous_selected_end: int | None = None
    section_headings: dict[int, str] = {0: ""}
    section_blocks: dict[int, list[str]] = {0: []}
    active_sections: dict[int, int] = {}
    next_section_id = 1
    for token in tokens:
        if token.map is None or token.type not in {"heading_open", "paragraph_open", "fence"}:
            continue
        start_line, end_line = token.map
        source_range = (start_line, end_line)
        if token.type == "heading_open":
            heading_level = int(token.tag.removeprefix("h"))
            active_sections = {
                level: section_id
                for level, section_id in active_sections.items()
                if level < heading_level
            }
            active_sections[heading_level] = next_section_id
            section_headings[next_section_id] = "\n".join(lines[start_line:end_line])
            section_blocks[next_section_id] = []
            next_section_id += 1
        section_id = active_sections[max(active_sections)] if active_sections else 0
        if source_range in selected_ranges or _is_within_navigation_range(
            source_range, navigation_ranges
        ):
            continue
        if token.type == "fence" and (
            previous_selected_end is None
            or not _only_blank_lines(lines, previous_selected_end, start_line)
        ):
            continue
        block = "\n".join(lines[start_line:end_line]).strip()
        if not block:
            continue
        if token.type == "fence" and blocks and blocks[-1][0] == section_id:
            _, previous_start_line, _, previous_block = blocks[-1]
            block = f"{previous_block}\n\n{block}"
            blocks[-1] = (section_id, previous_start_line, end_line, block)
            section_blocks[section_id][-1] = block
        else:
            blocks.append((section_id, start_line, end_line, block))
            section_blocks[section_id].append(block)
        selected_ranges.add(source_range)
        previous_selected_end = end_line
    section_scores = {
        section_id: _guidance_section_priority(section_headings[section_id], blocks)
        for section_id, blocks in section_blocks.items()
    }
    section_start_lines = {
        section_id: min(
            start_line
            for item_section_id, start_line, _, _ in blocks
            if item_section_id == section_id
        )
        for section_id in section_blocks
        if any(item_section_id == section_id for item_section_id, _, _, _ in blocks)
    }
    ranked_sections = sorted(
        section_start_lines,
        key=lambda section_id: (-section_scores[section_id], section_start_lines[section_id]),
    )
    selected_sections = _selected_sections(
        ranked_sections,
        section_scores,
        section_headings,
    )
    selected_blocks: list[str] = []
    for section_id, line_budget in selected_sections:
        section_blocks_in_order = [
            block for item_section_id, _, _, block in blocks if item_section_id == section_id
        ]
        selected_blocks.extend(_bounded_section_blocks(section_blocks_in_order, line_budget))
    return selected_blocks


def _selected_sections(
    ranked_sections: list[int],
    section_scores: dict[int, int],
    section_headings: dict[int, str],
) -> list[tuple[int, int]]:
    """Return bounded sections with one operational section when available."""
    positive_sections = [
        section_id for section_id in ranked_sections if section_scores[section_id] > 0
    ]
    candidate_sections = positive_sections or ranked_sections
    operational_sections = [
        section_id
        for section_id in candidate_sections
        if _operational_section_priority(section_headings[section_id]) is not None
    ]
    operational_section = min(
        operational_sections,
        key=lambda section_id: (
            _operational_section_priority(section_headings[section_id])
            if _operational_section_priority(section_headings[section_id]) is not None
            else len(_OPERATIONAL_HEADING_TERMS),
            candidate_sections.index(section_id),
        ),
        default=None,
    )
    if operational_section is not None:
        candidate_sections = [
            operational_section,
            *(section_id for section_id in candidate_sections if section_id != operational_section),
        ]
    if len(candidate_sections) == 1:
        return [(candidate_sections[0], MAX_GUIDANCE_LINES)]
    if len(candidate_sections) == 2:
        return [(candidate_sections[0], 16), (candidate_sections[1], 16)]
    return list(
        zip(candidate_sections[: len(_SECTION_LINE_BUDGETS)], _SECTION_LINE_BUDGETS, strict=True)
    )


def _operational_section_priority(heading: str) -> int | None:
    """Return the operator-usefulness rank for an executable guidance heading."""
    normalized_heading = heading.removeprefix("#").strip().casefold()
    return next(
        (
            priority
            for priority, term in enumerate(_OPERATIONAL_HEADING_TERMS)
            if term in normalized_heading
        ),
        None,
    )


def _bounded_section_blocks(blocks: list[str], line_budget: int) -> list[str]:
    """Return source-ordered blocks that fit one section's allocated line budget."""
    selected_blocks: list[str] = []
    selected_lines = 0
    for block in blocks:
        separator_lines = 1 if selected_blocks else 0
        block_lines = len(block.splitlines())
        if selected_lines + separator_lines + block_lines > line_budget:
            if not selected_blocks:
                return [block]
            break
        selected_blocks.append(block)
        selected_lines += separator_lines + block_lines
    return selected_blocks


def _guidance_section_priority(heading: str, blocks: list[str]) -> int:
    """Return a deterministic, content-aware priority for one guidance section."""
    normalized_heading = heading.removeprefix("#").strip().casefold()
    heading_score = sum(
        priority
        for required_terms, priority in _GUIDANCE_HEADING_PRIORITIES
        if all(term in normalized_heading for term in required_terms)
    )
    content = "\n".join(blocks[1:])
    instruction_bullets = sum(
        1
        for line in content.splitlines()
        if line.lstrip().startswith(("- ", "* ")) and _is_guidance_directive(line)
    )
    directive_lines = sum(1 for line in content.splitlines() if _is_guidance_directive(line))
    code_block_bonus = 5 if any(block.startswith("```") for block in blocks[1:]) else 0
    return (
        heading_score
        + min(instruction_bullets, 4) * 10
        + min(directive_lines, 4) * 5
        + code_block_bonus
    )


def _is_guidance_directive(line: str) -> bool:
    """Return whether a Markdown line starts with a common instruction verb."""
    normalized_line = line.strip().lstrip("-*> ").casefold()
    return normalized_line.startswith(_GUIDANCE_DIRECTIVE_PREFIXES)


def _is_within_navigation_range(
    source_range: tuple[int, int], navigation_ranges: list[tuple[int, int]]
) -> bool:
    """Return whether a source range is contained by a navigation-only list item."""
    start_line, end_line = source_range
    return any(start_line >= start and end_line <= end for start, end in navigation_ranges)


def _only_blank_lines(lines: list[str], start_line: int, end_line: int) -> bool:
    """Return whether the source range between two blocks has only blank lines."""
    return all(not line.strip() for line in lines[start_line:end_line])


def _truncate_first_block(block: str) -> tuple[str, bool, bool]:
    """Bound one oversized first block while preserving deterministic evidence."""
    block_lines = block.splitlines()
    line_truncated = len(block_lines) > MAX_GUIDANCE_LINES
    truncated_lines = block_lines[: MAX_GUIDANCE_LINES - 1] if line_truncated else block_lines
    candidate = "\n".join(truncated_lines)
    character_truncated = len(candidate) > MAX_GUIDANCE_CHARS
    if character_truncated:
        candidate = candidate[: MAX_GUIDANCE_CHARS - 3].rstrip() + "..."
    elif line_truncated:
        candidate = candidate.rstrip() + "\n..."
    return candidate, line_truncated, character_truncated
