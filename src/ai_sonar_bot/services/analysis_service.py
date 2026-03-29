"""Issue analysis service.

This module builds source context and coordinates LLM-backed issue analysis and
patch proposal work for a selected SonarQube issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.analysis import AnalysisClassification, IssueContext, PatchProposal
from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.providers.llm_client import (
    FixtureLLMClient,
    OpenAILLMClient,
    _write_solution_file,
)
from ai_sonar_bot.services.context_builder import ContextBuilder
from ai_sonar_bot.services.fix_generator import FixGenerator
from ai_sonar_bot.services.patch_applier import PatchApplier, PatchApplyError
from ai_sonar_bot.services.validator import Validator
from ai_sonar_bot.settings import SettingsError, load_openai_connection_config


@dataclass(frozen=True)
class AnalysisResult:
    """Capture the outcome of issue analysis.

    Attributes:
        summary: Human-readable analysis summary.
    """

    summary: str


class AnalysisService:
    """Analyze a selected issue and optionally propose or apply a patch.

    Args:
        repo_root: Repository root path.
        config: Loaded application configuration.
    """

    def __init__(self, repo_root: Path, config: AppConfig) -> None:
        """Initialize the analysis service.

        Args:
            repo_root: Repository root path.
            config: Loaded application configuration.
        """
        self.repo_root = repo_root
        self.config = config
        self.context_builder = ContextBuilder(repo_root, config)
        self.patch_applier = PatchApplier(repo_root)
        self.validator = Validator(repo_root)

    def analyze_issue(self, *, selected_issue: SonarIssue, dry_run: bool) -> AnalysisResult:
        """Analyze a selected issue.

        Args:
            selected_issue: Selected SonarQube issue.
            dry_run: Whether the current run is in dry-run mode.

        Returns:
            Structured analysis result for the selected issue.
        """
        context = self.context_builder.build(selected_issue)
        if context is None:
            return AnalysisResult(summary="Context unavailable for the selected issue.")
        if not dry_run:
            return AnalysisResult(
                summary=(
                    "Context ready from lines "
                    f"{context.snippet.start_line}-{context.snippet.end_line}."
                )
            )

        llm_client = self._build_llm_client()
        if llm_client is None:
            return AnalysisResult(
                summary=(
                    "Context ready from lines "
                    f"{context.snippet.start_line}-{context.snippet.end_line}."
                )
            )

        fix_generator = FixGenerator(llm_client)
        analysis = fix_generator.analyze(selected_issue, context)
        summary = (
            f"Analysis classification: {analysis.classification.value}. "
            f"Strategy: {analysis.proposed_strategy}"
        )
        if isinstance(llm_client, OpenAILLMClient):
            summary = (
                f"{summary}. Solution file: "
                f"{llm_client.solution_output_path.relative_to(self.repo_root)}"
            )
        if analysis.classification == AnalysisClassification.MANUAL:
            if isinstance(llm_client, OpenAILLMClient):
                _write_solution_file(
                    llm_client.solution_output_path,
                    issue_key=selected_issue.key,
                    decision="rejected",
                    rejection_reason=(
                        "Analysis classified the issue as manual; patch generation was skipped."
                    ),
                    clear_patch=True,
                )
            return AnalysisResult(
                summary=f"{summary}. Patch generation skipped because manual review is required."
            )
        if self.config.mock_llm_patch_path is None and not isinstance(llm_client, OpenAILLMClient):
            return AnalysisResult(summary=summary)

        patch = fix_generator.generate(selected_issue, context)
        if isinstance(llm_client, OpenAILLMClient):
            _write_solution_file(
                llm_client.solution_output_path,
                issue_key=selected_issue.key,
                decision="accepted",
            )
        summary = (
            f"{summary}. Proposed files: {', '.join(patch.files_touched)}. "
            f"MR title: {patch.mr_title}"
        )
        if not self.config.apply_patch_in_dry_run:
            return AnalysisResult(summary=summary)
        return AnalysisResult(
            summary=self._apply_and_validate_patch(
                summary=summary,
                fix_generator=fix_generator,
                selected_issue=selected_issue,
                context=context,
                initial_patch=patch,
            )
        )

    def _build_llm_client(self) -> FixtureLLMClient | OpenAILLMClient | None:
        """Build the configured LLM client for dry-run workflows.

        Returns:
            An LLM client instance, or ``None`` if no LLM backend is configured.
        """
        try:
            return OpenAILLMClient(
                load_openai_connection_config(),
                solution_output_path=self.repo_root / self.config.openai_solution_output_path,
            )
        except SettingsError:
            if self.config.mock_llm_analysis_path is None:
                return None
            return FixtureLLMClient(
                self.config.mock_llm_analysis_path,
                patch_fixture_path=self.config.mock_llm_patch_path,
            )

    def _apply_and_validate_patch(
        self,
        *,
        summary: str,
        fix_generator: FixGenerator,
        selected_issue: SonarIssue,
        context: IssueContext,
        initial_patch: PatchProposal,
    ) -> str:
        """Apply a patch locally and run configured validation commands.

        Args:
            summary: Existing summary text to extend.
            fix_generator: LLM-backed fix generator.
            selected_issue: Selected SonarQube issue.
            context: Built issue context.
            initial_patch: First generated patch proposal.

        Returns:
            Human-readable execution summary including validation outcome.
        """
        patch = initial_patch
        for attempt in range(self.config.max_retry_count + 1):
            snapshot = self._snapshot_files(patch.files_touched)
            try:
                self.patch_applier.apply(patch)
            except PatchApplyError as error:
                return f"{summary}. Patch apply failed: {error}"
            validation_result = self.validator.run(self.config.validation_commands)
            if validation_result.passed:
                if attempt == 0:
                    return (
                        f"{summary}. Patch applied locally in dry-run. {validation_result.summary}"
                    )
                return (
                    f"{summary}. Patch applied locally in dry-run. "
                    f"{validation_result.summary} after retry {attempt}."
                )
            self._restore_files(snapshot)
            if attempt >= self.config.max_retry_count:
                return (
                    f"{summary}. Patch applied locally in dry-run. "
                    f"{validation_result.summary} Retry attempts exhausted."
                )
            patch = fix_generator.generate(selected_issue, context)
        return summary

    def _snapshot_files(self, file_paths: list[str]) -> dict[Path, str | None]:
        """Capture file contents before applying a patch.

        Args:
            file_paths: Repository-relative file paths touched by the patch.

        Returns:
            A mapping from absolute file path to previous file content, or
            ``None`` when the file did not exist.
        """
        snapshot: dict[Path, str | None] = {}
        for file_path in file_paths:
            target = self.repo_root / file_path
            snapshot[target] = target.read_text(encoding="utf-8") if target.exists() else None
        return snapshot

    def _restore_files(self, snapshot: dict[Path, str | None]) -> None:
        """Restore files from a previously captured snapshot.

        Args:
            snapshot: Previously captured file content mapping.
        """
        for target, content in snapshot.items():
            if content is None:
                if target.exists():
                    target.unlink()
                continue
            target.write_text(content, encoding="utf-8")
