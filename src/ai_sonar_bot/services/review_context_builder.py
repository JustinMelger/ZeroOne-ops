"""Review context builder."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.review import (
    MergeRequestReviewCandidate,
    MergeRequestReviewContext,
    ReviewFileContext,
)
from ai_sonar_bot.providers.gitlab_review_client import GitLabReviewClient
from ai_sonar_bot.services.context_builder import (
    _format_with_line_numbers,
    _window_bounds,
)

HUNK_HEADER_PATTERN = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


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
                changed_files=changed_files,
            ),
            message="",
        )

    def _is_supported_path(self, file_path: str) -> bool:
        """Return whether a changed path is in scope for review."""
        if not self.config.review.supported_paths:
            return True
        return any(file_path.startswith(prefix) for prefix in self.config.review.supported_paths)


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
