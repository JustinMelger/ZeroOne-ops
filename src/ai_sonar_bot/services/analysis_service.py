"""Issue analysis service.

This module builds source context and coordinates LLM-backed issue analysis and
patch proposal work for a selected SonarQube issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai_sonar_bot.models.analysis import (
    AnalysisClassification,
    IssueContext,
    PatchProposal,
    ValidationCommandResult,
)
from ai_sonar_bot.models.config import AppConfig
from ai_sonar_bot.models.sonar import SonarIssue
from ai_sonar_bot.models.state import FailureDetails, FailureStage
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
        patch: Generated patch proposal, if one was produced.
        patch_applied: Whether a patch was applied to the working tree.
        validation_passed: Whether validation passed after patch application.
        failure: Structured failure details when analysis or validation fails.
    """

    summary: str
    patch: PatchProposal | None = None
    patch_applied: bool = False
    validation_passed: bool | None = None
    failure: FailureDetails | None = None


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

        llm_client = self._build_llm_client()
        if llm_client is None:
            return AnalysisResult(
                summary=(
                    "LLM backend not configured. Context ready from lines "
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
                summary=f"{summary}. Patch generation skipped because manual review is required.",
                validation_passed=False,
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
        should_apply_patch = not dry_run or self.config.apply_patch_in_dry_run
        if not should_apply_patch:
            return AnalysisResult(summary=summary, patch=patch)
        return self._apply_and_validate_patch(
            dry_run=dry_run,
            patch=patch,
            summary=summary,
            fix_generator=fix_generator,
            selected_issue=selected_issue,
            context=context,
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
        dry_run: bool,
        patch: PatchProposal,
        summary: str,
        fix_generator: FixGenerator,
        selected_issue: SonarIssue,
        context: IssueContext,
    ) -> AnalysisResult:
        """Apply a patch locally and run configured validation commands.

        Args:
            dry_run: Whether the current execution is a dry run.
            patch: Initial generated patch proposal.
            summary: Existing summary text to extend.
            fix_generator: LLM-backed fix generator.
            selected_issue: Selected SonarQube issue.
            context: Built issue context.

        Returns:
            Structured analysis result including validation outcome.
        """
        for attempt in range(self.config.max_retry_count + 1):
            snapshot = self._snapshot_files(patch.files_touched)
            try:
                self.patch_applier.apply(patch)
            except PatchApplyError as error:
                return AnalysisResult(
                    summary=f"{summary}. Patch apply failed: {error}",
                    patch=patch,
                    patch_applied=False,
                    validation_passed=False,
                    failure=FailureDetails(
                        stage=FailureStage.PATCH_APPLY,
                        message=f"Patch apply failed: {error}",
                        retry_count=attempt,
                    ),
                )
            validation_result = self.validator.run(self.config.validation_commands)
            if validation_result.passed:
                mode_label = "dry-run" if dry_run else "run"
                if attempt == 0:
                    return AnalysisResult(
                        summary=(
                            f"{summary}. Patch applied locally in {mode_label}. "
                            f"{validation_result.summary}"
                        ),
                        patch=patch,
                        patch_applied=True,
                        validation_passed=True,
                    )
                return AnalysisResult(
                    summary=(
                        f"{summary}. Patch applied locally in {mode_label}. "
                        f"{validation_result.summary} after retry {attempt}."
                    ),
                    patch=patch,
                    patch_applied=True,
                    validation_passed=True,
                )
            self._restore_files(snapshot)
            if attempt >= self.config.max_retry_count:
                mode_label = "dry-run" if dry_run else "run"
                return AnalysisResult(
                    summary=(
                        f"{summary}. Patch applied locally in {mode_label}. "
                        f"{validation_result.summary} Retry attempts exhausted."
                    ),
                    patch=patch,
                    patch_applied=False,
                    validation_passed=False,
                    failure=self._build_validation_failure(
                        validation_summary=validation_result.summary,
                        retry_count=attempt,
                        command_result=validation_result.results[-1]
                        if validation_result.results
                        else None,
                    ),
                )
            patch = fix_generator.generate(selected_issue, context)
        return AnalysisResult(summary=summary, patch=patch)

    def _build_validation_failure(
        self,
        *,
        validation_summary: str,
        retry_count: int,
        command_result: ValidationCommandResult | None,
    ) -> FailureDetails:
        """Build structured validation failure details.

        Args:
            validation_summary: Aggregate validation summary.
            retry_count: Retries consumed before failure.
            command_result: Final failed command result, if available.

        Returns:
            Structured failure details for persistence and logging.
        """
        stdout_excerpt = None
        stderr_excerpt = None
        failed_command = None
        exit_code = None
        if command_result is not None:
            failed_command = command_result.command
            exit_code = command_result.exit_code
            stdout_excerpt = _truncate_output(command_result.stdout)
            stderr_excerpt = _truncate_output(command_result.stderr)
        return FailureDetails(
            stage=FailureStage.VALIDATION,
            message=validation_summary,
            retry_count=retry_count,
            validation_summary=validation_summary,
            failed_command=failed_command,
            exit_code=exit_code,
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
        )

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


def _truncate_output(value: str, limit: int = 500) -> str | None:
    """Truncate command output for state persistence.

    Args:
        value: Raw command output.
        limit: Maximum number of characters to keep.

    Returns:
        Trimmed output string, or ``None`` when empty.
    """
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit]}..."
