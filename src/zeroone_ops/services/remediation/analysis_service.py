"""Issue analysis service.

This module builds source context and coordinates LLM-backed issue analysis and
patch proposal work for a selected SonarQube issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.analysis import (
    AnalysisClassification,
    IssueContext,
    PatchProposal,
    ValidationResult,
)
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import FailureDetails, FailureStage
from zeroone_ops.providers.llm_client import (
    FixtureLLMClient,
    LLMClientError,
    OpenAILLMClient,
)
from zeroone_ops.services.remediation.edit_renderer import (
    EditRenderer,
    EditRenderError,
)
from zeroone_ops.services.remediation.fix_generator import FixGenerator
from zeroone_ops.services.remediation.patch_applier import PatchApplier
from zeroone_ops.services.remediation.patch_execution_service import (
    PatchExecutionService,
)
from zeroone_ops.services.remediation.solution_artifact_service import (
    SolutionArtifactService,
)
from zeroone_ops.services.remediation.validator import Validator
from zeroone_ops.services.shared.context_builder import ContextBuilder
from zeroone_ops.services.shared.workspace_snapshot import (
    WorkspaceSnapshot,
    WorkspaceSnapshotService,
)
from zeroone_ops.settings import SettingsError, load_openai_connection_config


@dataclass(frozen=True)
class AnalysisResult:
    """Capture the outcome of issue analysis.

    Attributes:
        summary: Human-readable analysis summary.
        patch: Generated patch proposal, if one was produced.
        patch_applied: Whether a patch was applied to the working tree.
        validation_passed: Whether validation passed after patch application.
        validation_result: Captured validation result when validation was run.
        failure: Structured failure details when analysis or validation fails.
    """

    summary: str
    patch: PatchProposal | None = None
    patch_applied: bool = False
    validation_passed: bool | None = None
    validation_result: ValidationResult | None = None
    failure: FailureDetails | None = None
    workspace_snapshot: WorkspaceSnapshot | None = None


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
        self.edit_renderer = EditRenderer(repo_root)
        self.patch_applier = PatchApplier(repo_root)
        self.validator = Validator(repo_root)
        self.workspace_snapshot_service = WorkspaceSnapshotService(repo_root)
        self.patch_execution_service = PatchExecutionService(
            config=config,
            patch_applier=self.patch_applier,
            validator=self.validator,
            workspace_snapshot_service=self.workspace_snapshot_service,
        )

    def analyze_issue(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        dry_run: bool,
    ) -> AnalysisResult:
        """Analyze a selected execution target.

        Args:
            selected_issue: Selected remediation execution target.
            dry_run: Whether the current run is in dry-run mode.

        Returns:
            Structured analysis result for the selected issue.
        """
        context = self.context_builder.build(selected_issue)
        if context is None:
            return AnalysisResult(summary="Context unavailable for the selected issue.")
        return self.analyze_issue_with_context(
            selected_issue=selected_issue,
            context=context,
            dry_run=dry_run,
        )

    def analyze_issue_with_context(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        context: IssueContext,
        dry_run: bool,
    ) -> AnalysisResult:
        """Analyze a selected execution target with prebuilt source context."""
        llm_client = self._build_llm_client()
        if llm_client is None:
            return AnalysisResult(
                summary=(
                    "LLM backend not configured. Context ready from lines "
                    f"{context.snippet.start_line}-{context.snippet.end_line}."
                )
            )

        fix_generator = FixGenerator(llm_client)
        artifact_service = SolutionArtifactService(
            llm_client.solution_output_path if isinstance(llm_client, OpenAILLMClient) else None
        )
        analysis = fix_generator.analyze(selected_issue, context)
        artifact_service.write_analysis(issue_key=selected_issue.source_ref, analysis=analysis)
        summary = (
            f"Analysis classification: {analysis.classification.value}. "
            f"Strategy: {analysis.proposed_strategy}"
        )
        relative_artifact_path = artifact_service.relative_path(self.repo_root)
        if relative_artifact_path is not None:
            summary = f"{summary}. Solution file: {relative_artifact_path}"
        if analysis.classification == AnalysisClassification.MANUAL:
            artifact_service.write_manual_rejection(issue_key=selected_issue.source_ref)
            return AnalysisResult(
                summary=f"{summary}. Patch generation skipped because manual review is required.",
                validation_passed=False,
            )
        try:
            patch = self._generate_patch(
                fix_generator=fix_generator,
                selected_issue=selected_issue,
                context=context,
                artifact_service=artifact_service,
            )
        except EditRenderError as error:
            return AnalysisResult(
                summary=f"{summary}. Structured edit could not be rendered safely: {error}",
                validation_passed=False,
                failure=FailureDetails(
                    stage=FailureStage.ANALYSIS,
                    message=f"Structured edit could not be rendered safely: {error}",
                ),
            )
        except LLMClientError as error:
            return AnalysisResult(
                summary=f"{summary}. Structured edit generation failed: {error}",
                validation_passed=False,
                failure=FailureDetails(
                    stage=FailureStage.ANALYSIS,
                    message=f"Structured edit generation failed: {error}",
                ),
            )
        artifact_service.write_patch(issue_key=selected_issue.source_ref, patch=patch)
        summary = (
            f"{summary}. Proposed files: {', '.join(patch.files_touched)}. "
            f"MR title: {patch.mr_title}. "
            "Diff rendered by bot from structured edit proposal."
        )
        should_apply_patch = not dry_run or self.config.apply_patch_in_dry_run
        if not should_apply_patch:
            return AnalysisResult(summary=summary, patch=patch)
        execution_result = self.patch_execution_service.execute(
            dry_run=dry_run,
            patch=patch,
            summary=summary,
            fix_generator=fix_generator,
            selected_issue=selected_issue,
            context=context,
            patch_factory=lambda **kwargs: self._generate_patch(
                artifact_service=artifact_service,
                **kwargs,
            ),
        )
        return AnalysisResult(
            summary=execution_result.summary,
            patch=execution_result.patch,
            patch_applied=execution_result.patch_applied,
            validation_passed=execution_result.validation_passed,
            validation_result=execution_result.validation_result,
            failure=execution_result.failure,
            workspace_snapshot=execution_result.workspace_snapshot,
        )

    def _build_llm_client(self) -> FixtureLLMClient | OpenAILLMClient | None:
        """Build the configured LLM client for dry-run workflows.

        Returns:
            An LLM client instance, or ``None`` if no LLM backend is configured.
        """
        try:
            return OpenAILLMClient(
                load_openai_connection_config(),
                solution_output_path=self._solution_output_path(),
            )
        except SettingsError:
            if self.config.mock_llm_analysis_path is None:
                return None
            return FixtureLLMClient(
                self.config.mock_llm_analysis_path,
                structured_edit_fixture_path=self.config.mock_llm_edit_path,
            )

    def _solution_output_path(self) -> Path | None:
        """Return the solution artifact path for the current execution mode."""
        if self.config.execution_mode == "ci" and not self.config.write_solution_artifacts_in_ci:
            return None
        return self.repo_root / self.config.openai_solution_output_path

    def _generate_patch(
        self,
        *,
        fix_generator: FixGenerator,
        selected_issue: RemediationExecutionTarget,
        context: IssueContext,
        artifact_service: SolutionArtifactService,
    ) -> PatchProposal:
        """Generate a patch proposal from a structured edit.

        Args:
            fix_generator: LLM-backed fix generator.
            selected_issue: Selected SonarQube issue.
            context: Built issue context.
            artifact_service: Artifact persistence service for analysis outputs.

        Returns:
            The generated patch proposal.
        """
        structured_edit = fix_generator.generate_structured_edit(selected_issue, context)
        artifact_service.write_structured_edit(
            issue_key=selected_issue.source_ref,
            structured_edit=structured_edit,
        )
        target_files = {edit.file_path for edit in structured_edit.edits}
        if len(target_files) != 1:
            raise EditRenderError(
                "V1 automation only supports structured edits that touch exactly one file."
            )
        return self.edit_renderer.render(structured_edit)
