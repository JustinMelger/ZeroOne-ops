"""Review context builder."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.review import (
    MergeRequestReviewCandidate,
    MergeRequestReviewContext,
    RemediationReviewContext,
    RepositoryGuidanceContext,
    ReviewFileContext,
)
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient
from ai_sonar_bot.services.context_builder import (
    _format_with_line_numbers,
    _window_bounds,
)
from ai_sonar_bot.services.review_helper_context import build_same_file_helper_context

HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
SECTION_HEADER_PATTERN = re.compile(r"^## (?P<title>.+)$", re.MULTILINE)
TARGET_BULLET_PATTERN = re.compile(r"^- (?P<label>[^:]+): (?P<value>.+)$")
GUIDANCE_HEADING_PATTERN = re.compile(r"^(#+)\s+.+$")
GUIDANCE_BULLET_PATTERN = re.compile(r"^([-*]|\d+\.)\s+.+$")
GUIDANCE_PATHS = (
    "AGENT.md",
    "CONTRIBUTING.md",
    "README.md",
    "docs/engineering-standards.md",
)
GUIDANCE_GLOBS = ("docs/technical-design*.md",)
MAX_GUIDANCE_FILES = 4
MAX_GUIDANCE_LINES = 16
MAX_GUIDANCE_CHARS = 1_200
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReviewContextBuildResult:
    """Capture the result of building review context."""

    context: MergeRequestReviewContext | None
    message: str


class ReviewContextBuilder:
    """Build deterministic review context from MR diffs and local files."""

    def __init__(
        self,
        repo_root: Path,
        config: AppConfig,
        review_client: GitLabReviewClient,
    ) -> None:
        """Initialize the review context builder."""
        self.repo_root = repo_root
        self.config = config
        self.review_client = review_client

    def build(
        self,
        merge_request: MergeRequestReviewCandidate,
        *,
        project_id: str,
    ) -> ReviewContextBuildResult:
        """Build review context for one merge request."""
        detailed_merge_request = self.review_client.get_merge_request(
            project_id=project_id,
            merge_request_iid=merge_request.iid,
        )
        supported_changes = [
            change
            for change in detailed_merge_request.changes
            if not change.deleted_file and self._is_supported_path(change.new_path)
        ]
        if len(supported_changes) == 0:
            return ReviewContextBuildResult(
                context=None,
                message=(
                    "Could not build review context. "
                    "The merge request has no supported non-deleted changed files."
                ),
            )
        if len(supported_changes) > self.config.review.max_changed_files:
            return ReviewContextBuildResult(
                context=None,
                message=(
                    "Could not build review context. "
                    f"The merge request changes {len(supported_changes)} supported files, "
                    f"which exceeds the v1 limit of {self.config.review.max_changed_files}."
                ),
            )

        changed_files: list[ReviewFileContext] = []
        remaining_helper_lines = self.config.review.max_followed_helper_lines_per_review
        for change in supported_changes:
            target = self.repo_root / change.new_path
            if not target.exists():
                return ReviewContextBuildResult(
                    context=None,
                    message=(
                        "Could not build review context. "
                        f"Changed file is missing in the local repository: {change.new_path}"
                    ),
                )
            raw_content = target.read_text(encoding="utf-8")
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
            snippet_lines = lines[start_line - 1 : end_line]
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
                    diff=change.diff,
                    start_line=start_line,
                    end_line=end_line,
                    content=_format_with_line_numbers(
                        start_line=start_line,
                        lines=snippet_lines,
                    ),
                    full_file_included=start_line == 1 and end_line == max(line_count, 1),
                    truncated=not (start_line == 1 and end_line == max(line_count, 1)),
                    new_file=change.new_file,
                    deleted_file=change.deleted_file,
                    renamed_file=change.renamed_file,
                    helper_context=helper_context,
                )
            )

        return ReviewContextBuildResult(
            context=MergeRequestReviewContext(
                mr_iid=detailed_merge_request.iid,
                title=detailed_merge_request.title,
                description=detailed_merge_request.description,
                source_branch=detailed_merge_request.source_branch,
                target_branch=detailed_merge_request.target_branch,
                web_url=detailed_merge_request.web_url,
                head_sha=detailed_merge_request.head_sha,
                draft=detailed_merge_request.draft,
                author_username=detailed_merge_request.author_username,
                remediation_context=_parse_remediation_context(detailed_merge_request.description),
                repository_guidance=self._load_repository_guidance(),
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

    def _load_repository_guidance(self) -> list[RepositoryGuidanceContext]:
        """Load a few bounded repository guidance excerpts when available."""
        guidance_paths: list[Path] = []
        for relative_path in GUIDANCE_PATHS:
            target = self.repo_root / relative_path
            if target.exists() and target.is_file():
                guidance_paths.append(target)
        for pattern in GUIDANCE_GLOBS:
            for target in sorted(self.repo_root.glob(pattern)):
                if target.is_file() and target not in guidance_paths:
                    guidance_paths.append(target)

        guidance_entries: list[RepositoryGuidanceContext] = []
        for target in guidance_paths[:MAX_GUIDANCE_FILES]:
            summary = _extract_guidance_summary(target)
            if summary is None:
                continue
            guidance_entries.append(
                RepositoryGuidanceContext(
                    file_path=target.relative_to(self.repo_root).as_posix(),
                    summary=summary,
                )
            )
        return guidance_entries


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
