"""Solution artifact service.

This module owns optional local persistence of OpenAI analysis outputs.
"""

from __future__ import annotations

from pathlib import Path

from zeroone_ops.models.analysis import IssueAnalysis, PatchProposal, StructuredEditProposal
from zeroone_ops.utils.solution_artifacts import write_solution_artifact


class SolutionArtifactService:
    """Persist optional local solution artifacts for debugging.

    Args:
        output_path: Optional file path where artifacts should be written.
    """

    def __init__(self, output_path: Path | None) -> None:
        """Initialize the solution artifact service.

        Args:
            output_path: Optional file path where artifacts should be written.
        """
        self.output_path = output_path

    def relative_path(self, repo_root: Path) -> Path | None:
        """Return the output path relative to the repository root when possible."""
        if self.output_path is None:
            return None
        return self.output_path.relative_to(repo_root)

    def write_analysis(self, *, issue_key: str, analysis: IssueAnalysis) -> None:
        """Persist issue analysis when artifact output is enabled."""
        if self.output_path is None:
            return
        write_solution_artifact(
            self.output_path,
            issue_key=issue_key,
            analysis=analysis,
        )

    def write_patch(self, *, issue_key: str, patch: PatchProposal) -> None:
        """Persist rendered patch metadata when artifact output is enabled."""
        if self.output_path is None:
            return
        write_solution_artifact(
            self.output_path,
            issue_key=issue_key,
            patch=patch,
            decision="accepted",
        )

    def write_structured_edit(
        self,
        *,
        issue_key: str,
        structured_edit: StructuredEditProposal,
    ) -> None:
        """Persist structured edit data when artifact output is enabled."""
        if self.output_path is None:
            return
        write_solution_artifact(
            self.output_path,
            issue_key=issue_key,
            structured_edit=structured_edit,
        )

    def write_manual_rejection(self, *, issue_key: str) -> None:
        """Persist manual-classification rejection when artifact output is enabled."""
        if self.output_path is None:
            return
        write_solution_artifact(
            self.output_path,
            issue_key=issue_key,
            decision="rejected",
            rejection_reason=(
                "Analysis classified the issue as manual; patch generation was skipped."
            ),
            clear_patch=True,
        )
