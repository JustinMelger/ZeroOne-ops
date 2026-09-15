"""Review context builder."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.review import (
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    RemediationReviewContext,
    ReviewFileContext,
)
from zeroone_ops.services.review.context.review_function_context import (
    select_function_aware_window,
)
from zeroone_ops.services.review.context.review_helper_context import (
    build_same_file_helper_context,
)
from zeroone_ops.services.shared.context_builder import (
    _format_with_line_numbers,
    _window_bounds,
)
from zeroone_ops.services.shared.repository_guidance import load_repository_guidance

HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
SECTION_HEADER_PATTERN = re.compile(r"^## (?P<title>.+)$", re.MULTILINE)
TARGET_BULLET_PATTERN = re.compile(r"^- (?P<label>[^:]+): (?P<value>.+)$")
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewContextBuildResult:
    """Capture the result of building review context."""

    context: ChangeRequestReviewContext | None
    message: str


class ReviewContextBuilder:
    """Build deterministic review context from change-request diffs and local files."""

    def __init__(
        self,
        repo_root: Path,
        config: AppConfig,
    ) -> None:
        """Initialize the review context builder."""
        self.repo_root = repo_root
        self.config = config

    def build(
        self,
        change_request: ChangeRequestReviewCandidate,
    ) -> ReviewContextBuildResult:
        """Build review context for one change request."""
        candidate_changes = [
            change
            for change in change_request.changes
            if not change.deleted_file and self._is_supported_path(change.new_path)
        ]
        if len(candidate_changes) == 0:
            return ReviewContextBuildResult(
                context=None,
                message=(
                    "Could not build review context. "
                    "The change request has no supported non-deleted changed files."
                ),
            )
        if len(candidate_changes) > self.config.review.max_changed_files:
            return ReviewContextBuildResult(
                context=None,
                message=(
                    "Could not build review context. "
                    f"The change request changes {len(candidate_changes)} supported files, "
                    f"which exceeds the v1 limit of {self.config.review.max_changed_files}."
                ),
            )

        changed_files: list[ReviewFileContext] = []
        remaining_helper_lines = self.config.review.max_followed_helper_lines_per_review
        unreadable_paths: list[str] = []
        for change in candidate_changes:
            target = self.repo_root / change.new_path
            if not target.exists():
                return ReviewContextBuildResult(
                    context=None,
                    message=(
                        "Could not build review context. "
                        f"Changed file is missing in the local repository: {change.new_path}"
                    ),
                )
            try:
                raw_content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                unreadable_paths.append(change.new_path)
                LOGGER.info(
                    "review context skipped unreadable changed file",
                    extra={"file_path": change.new_path},
                )
                continue
            lines = raw_content.splitlines()
            line_count = len(lines)
            changed_start, changed_end = _changed_line_window(change.diff, line_count)
            start_line, end_line = _window_bounds(
                issue_line=changed_start,
                line_count=line_count,
                lines_before=self.config.review.max_context_lines_before,
                lines_after=max(
                    self.config.review.max_context_lines_after,
                    changed_end - changed_start,
                ),
            )
            function_window = select_function_aware_window(
                file_path=change.new_path,
                raw_content=raw_content,
                line_count=line_count,
                changed_start=changed_start,
                changed_end=changed_end,
                fallback_start_line=start_line,
                fallback_end_line=end_line,
                enable_function_context=self.config.review.enable_function_context,
                max_function_context_lines=self.config.review.max_function_context_lines,
            )
            start_line = function_window.start_line
            end_line = function_window.end_line
            content = _format_line_ranges_with_numbers(
                lines=lines,
                line_ranges=function_window.line_ranges,
            )
            full_file_included = (
                len(function_window.line_ranges) == 1
                and start_line == 1
                and end_line == max(line_count, 1)
            )
            helper_context, consumed_helper_lines = build_same_file_helper_context(
                repo_root=self.repo_root,
                file_path=change.new_path,
                raw_content=raw_content,
                lines=lines,
                changed_start=changed_start,
                changed_end=changed_end,
                enable_helper_following=self.config.review.enable_helper_following,
                log_helper_following=self.config.review.log_helper_following,
                max_followed_helpers_per_function=(
                    self.config.review.max_followed_helpers_per_function
                ),
                max_followed_helper_lines=min(
                    self.config.review.max_followed_helper_lines,
                    remaining_helper_lines,
                ),
                supported_paths=self.config.review.supported_paths,
                ignored_paths=self.config.review.ignored_paths,
            )
            remaining_helper_lines = max(0, remaining_helper_lines - consumed_helper_lines)
            changed_files.append(
                ReviewFileContext(
                    file_path=change.new_path,
                    old_path=change.old_path,
                    new_path=change.new_path,
                    diff=change.diff,
                    start_line=start_line,
                    end_line=end_line,
                    content=content,
                    full_file_included=full_file_included,
                    truncated=not full_file_included,
                    new_file=change.new_file,
                    deleted_file=change.deleted_file,
                    renamed_file=change.renamed_file,
                    helper_context=helper_context,
                )
            )

        if len(changed_files) == 0:
            unreadable_detail = (
                f" Unreadable files: {', '.join(unreadable_paths)}." if unreadable_paths else ""
            )
            return ReviewContextBuildResult(
                context=None,
                message=(
                    "Could not build review context. "
                    "The change request has no readable supported non-deleted changed files."
                    f"{unreadable_detail}"
                ),
            )

        return ReviewContextBuildResult(
            context=ChangeRequestReviewContext(
                change_request_number=change_request.change_request_number,
                title=change_request.title,
                description=change_request.description,
                source_branch=change_request.source_branch,
                target_branch=change_request.target_branch,
                web_url=change_request.web_url,
                head_sha=change_request.head_sha,
                draft=change_request.draft,
                author_username=change_request.author_username,
                diff_refs=change_request.diff_refs,
                remediation_context=_parse_remediation_context(change_request.description),
                repository_guidance=load_repository_guidance(
                    self.repo_root,
                    configured_paths=self.config.repository_guidance_paths,
                ),
                changed_files=changed_files,
            ),
            message="",
        )

    def _is_supported_path(self, file_path: str) -> bool:
        """Return whether a changed path is in scope for review."""
        if any(file_path.startswith(prefix) for prefix in self.config.review.ignored_paths):
            return False
        if not self.config.review.supported_paths:
            return True
        return any(file_path.startswith(prefix) for prefix in self.config.review.supported_paths)


def _parse_remediation_context(description: str | None) -> RemediationReviewContext | None:
    """Parse bot-authored remediation metadata from an MR description when present."""
    if not description:
        return None

    sections = _parse_markdown_sections(description)
    target_section = sections.get("Remediation Target")
    if target_section is None:
        return None

    summary = _normalize_section_text(sections.get("Summary"))
    validation_summary = _parse_single_bullet_or_text(sections.get("Validation"))
    notes = _parse_single_bullet_or_text(sections.get("Notes"))

    context = RemediationReviewContext(
        summary=summary,
        validation_summary=validation_summary,
        notes=notes,
    )
    for raw_line in target_section.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = TARGET_BULLET_PATTERN.match(line)
        if match is None:
            continue
        label = match.group("label").strip()
        value = _strip_markdown_code(match.group("value").strip())
        if label == "Source":
            context.source = value
        elif label == "Source ID":
            context.source_id = value
        elif label == "Rule":
            context.rule_id = value
        elif label == "Severity":
            context.severity = value
        elif label == "Type":
            context.remediation_type = value
        elif label == "File":
            context.file_path = value
        elif label == "Line":
            context.line = _parse_optional_line(value)
        elif label == "Message":
            context.message = value
        elif context.item_reference is None:
            context.item_reference_label = label
            context.item_reference = value

    if all(
        value is None
        for value in (
            context.summary,
            context.source,
            context.source_id,
            context.item_reference,
            context.rule_id,
            context.severity,
            context.remediation_type,
            context.file_path,
            context.line,
            context.message,
            context.validation_summary,
            context.notes,
        )
    ):
        return None
    return context


def _format_line_ranges_with_numbers(
    *,
    lines: list[str],
    line_ranges: tuple[tuple[int, int], ...],
) -> str:
    """Format one or more source ranges with numbered lines and omitted gaps."""
    if not line_ranges:
        return ""

    formatted_parts: list[str] = []
    for index, (start_line, end_line) in enumerate(line_ranges):
        range_lines = lines[start_line - 1 : end_line]
        if formatted_parts:
            previous_end = line_ranges[index - 1][1]
            if start_line > previous_end + 1:
                formatted_parts.append(" ...")
        formatted_parts.append(
            _format_with_line_numbers(
                start_line=start_line,
                lines=range_lines,
            )
        )
    return "\n".join(part for part in formatted_parts if part)


def _parse_markdown_sections(text: str) -> dict[str, str]:
    """Split a markdown document into second-level heading sections."""
    matches = list(SECTION_HEADER_PATTERN.finditer(text))
    if not matches:
        return {}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group("title").strip()] = text[start:end].strip()
    return sections


def _normalize_section_text(text: str | None) -> str | None:
    """Collapse a markdown section into one normalized line when present."""
    if text is None:
        return None
    normalized = " ".join(line.strip() for line in text.splitlines() if line.strip())
    return normalized or None


def _parse_single_bullet_or_text(text: str | None) -> str | None:
    """Normalize one short bullet-style section."""
    normalized = _normalize_section_text(text)
    if normalized is None:
        return None
    if normalized.startswith("- "):
        return normalized[2:].strip() or None
    return normalized


def _strip_markdown_code(value: str) -> str:
    """Strip simple markdown code fences from scalar values."""
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        return value[1:-1]
    return value


def _parse_optional_line(value: str) -> int | None:
    """Parse one optional integer line value from MR metadata."""
    if value.lower() == "n/a":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _changed_line_window(diff: str | None, line_count: int) -> tuple[int, int]:
    """Return the approximate changed-line range in the new file."""
    if line_count <= 0:
        return 1, 1
    if not diff:
        return 1, line_count

    start_line: int | None = None
    end_line: int | None = None
    for raw_line in diff.splitlines():
        match = HUNK_HEADER_PATTERN.match(raw_line)
        if match is None:
            continue
        hunk_start = int(match.group(1))
        hunk_length = int(match.group(2) or "1")
        hunk_end = max(hunk_start, hunk_start + max(hunk_length - 1, 0))
        start_line = hunk_start if start_line is None else min(start_line, hunk_start)
        end_line = hunk_end if end_line is None else max(end_line, hunk_end)

    if start_line is None or end_line is None:
        return 1, line_count
    return start_line, min(end_line, line_count)
