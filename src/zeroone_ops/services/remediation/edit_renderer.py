"""Structured edit rendering service.

This module turns exact text-edit proposals into unified diff patches that can
be applied by the existing patch pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

from zeroone_ops.models.analysis import PatchProposal, StructuredEditProposal, TextEdit


class EditRenderError(RuntimeError):
    """Raised when a structured edit proposal cannot be rendered safely."""


@dataclass(frozen=True)
class _TextMatch:
    """Represent one exact text match in a file.

    Attributes:
        start: Start offset in the source content.
        end: End offset in the source content.
        line_number: 1-based line number where the match begins.
    """

    start: int
    end: int
    line_number: int


class EditRenderer:
    """Render structured edit proposals into unified diffs.

    Args:
        repo_root: Repository root containing the files to edit.
    """

    def __init__(self, repo_root: Path) -> None:
        """Initialize the edit renderer.

        Args:
            repo_root: Repository root containing the files to edit.
        """
        self.repo_root = repo_root

    def render(self, proposal: StructuredEditProposal) -> PatchProposal:
        """Render a structured edit proposal to a patch proposal.

        Args:
            proposal: Structured edit proposal to render.

        Returns:
            Patch proposal with a bot-rendered unified diff.

        Raises:
            EditRenderError: If the proposal is unsupported or ambiguous.
        """
        if not proposal.edits:
            raise EditRenderError("Structured edit proposal does not contain any edits.")

        files_touched = sorted({edit.file_path for edit in proposal.edits})
        if len(files_touched) != 1:
            raise EditRenderError(
                "Structured edit rendering currently supports exactly one target file."
            )

        target_file = files_touched[0]
        source_path = self.repo_root / target_file
        if not source_path.exists():
            raise EditRenderError(f"Target file does not exist: {target_file}")

        original_text = source_path.read_text(encoding="utf-8")
        updated_text = original_text
        for edit in proposal.edits:
            updated_text = self._apply_edit(updated_text, edit)

        if updated_text == original_text:
            raise EditRenderError("Structured edit proposal did not change the target file.")

        diff_lines = unified_diff(
            original_text.splitlines(keepends=True),
            updated_text.splitlines(keepends=True),
            fromfile=f"a/{target_file}",
            tofile=f"b/{target_file}",
        )
        unified_diff_text = "".join(diff_lines)
        return PatchProposal(
            issue_key=proposal.issue_key,
            files_touched=files_touched,
            unified_diff=(f"diff --git a/{target_file} b/{target_file}\n{unified_diff_text}"),
            commit_message=proposal.commit_message,
            change_request_title=proposal.change_request_title,
            change_request_description=proposal.change_request_description,
            remediation_intent=proposal.remediation_intent,
        )

    def _apply_edit(self, content: str, edit: TextEdit) -> str:
        """Apply one exact text edit to file content.

        Args:
            content: Current file content.
            edit: Exact text replacement to apply.

        Returns:
            Updated file content.

        Raises:
            EditRenderError: If the edit cannot be resolved safely.
        """
        matches = _find_matches(content, edit.search_text)
        if not matches:
            raise EditRenderError(f"Could not find exact search text in {edit.file_path!r}.")

        selected_match = self._select_match(matches, edit)
        return content[: selected_match.start] + edit.replace_text + content[selected_match.end :]

    def _select_match(self, matches: list[_TextMatch], edit: TextEdit) -> _TextMatch:
        """Select the correct text match for an edit.

        Args:
            matches: Exact search-text matches in the file.
            edit: Text edit being applied.

        Returns:
            The selected text match.

        Raises:
            EditRenderError: If the edit is ambiguous.
        """
        if len(matches) == 1:
            return matches[0]
        if edit.line_hint is None:
            raise EditRenderError(f"Search text in {edit.file_path!r} matched multiple locations.")

        hinted_matches = [match for match in matches if match.line_number == edit.line_hint]
        if len(hinted_matches) != 1:
            raise EditRenderError(
                f"Line hint {edit.line_hint} did not uniquely identify the edit in "
                f"{edit.file_path!r}."
            )
        return hinted_matches[0]


def _find_matches(content: str, search_text: str) -> list[_TextMatch]:
    """Find exact text matches within file content.

    Args:
        content: File content to search.
        search_text: Exact text to match.

    Returns:
        All exact text matches with offsets and starting line numbers.

    Raises:
        EditRenderError: If the search text is empty.
    """
    if search_text == "":
        raise EditRenderError("Structured edit search_text must not be empty.")

    matches: list[_TextMatch] = []
    start = 0
    while True:
        index = content.find(search_text, start)
        if index == -1:
            return matches
        line_number = content.count("\n", 0, index) + 1
        matches.append(
            _TextMatch(
                start=index,
                end=index + len(search_text),
                line_number=line_number,
            )
        )
        start = index + 1
