"""Issue analysis service.

This module builds source context and coordinates LLM-backed issue analysis and
patch proposal work for one selected remediation target.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from zeroone_ops.models.analysis import (
    IssueContext,
    PatchProposal,
    SemanticSafetyDecision,
    ValidationComparison,
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
from zeroone_ops.services.remediation.remediation_context_builder import (
    RemediationContextBuilder,
)
from zeroone_ops.services.remediation.semantic_safety_gate_service import (
    SemanticSafetyGateService,
)
from zeroone_ops.services.remediation.solution_artifact_service import (
    SolutionArtifactService,
)
from zeroone_ops.services.remediation.validator import Validator
from zeroone_ops.services.shared.runtime_workspace import RuntimeWorkspacePolicy
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
    validation_comparison: ValidationComparison | None = None
    failure: FailureDetails | None = None
    workspace_snapshot: WorkspaceSnapshot | None = None
    semantic_safety: SemanticSafetyDecision | None = None
    terminal_rejection_stage: FailureStage | None = None


class AnalysisService:
    """Analyze a selected issue and optionally propose or apply a patch.

    Args:
        repo_root: Repository root path.
        config: Loaded application configuration.
        runtime_workspace_policy: Shared rule for generated runtime outputs.
    """

    def __init__(
        self,
        repo_root: Path,
        config: AppConfig,
        *,
        runtime_workspace_policy: RuntimeWorkspacePolicy | None = None,
    ) -> None:
        """Initialize the analysis service.

        Args:
            repo_root: Repository root path.
            config: Loaded application configuration.
            runtime_workspace_policy: Shared rule for generated runtime outputs.
        """
        self.repo_root = repo_root
        self.config = config
        self.context_builder = RemediationContextBuilder(repo_root, config)
        self.edit_renderer = EditRenderer(repo_root)
        self.patch_applier = PatchApplier(repo_root)
        self.validator = Validator(repo_root)
        self.workspace_snapshot_service = WorkspaceSnapshotService(repo_root)
        runtime_workspace_policy = runtime_workspace_policy or RuntimeWorkspacePolicy.from_config(
            config=config,
            repo_root=repo_root,
        )
        self.patch_execution_service = PatchExecutionService(
            config=config,
            patch_applier=self.patch_applier,
            validator=self.validator,
            workspace_snapshot_service=self.workspace_snapshot_service,
            runtime_workspace_policy=runtime_workspace_policy,
        )
        self.semantic_safety_gate_service = SemanticSafetyGateService()

    def analyze_issue(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        dry_run: bool,
        pre_patch_handler: Callable[[PatchProposal], FailureDetails | None] | None = None,
    ) -> AnalysisResult:
        """Analyze a selected execution target.

        Args:
            selected_issue: Selected remediation execution target.
            dry_run: Whether the current run is in dry-run mode.
            pre_patch_handler: Optional live-execution preparation before patch application.

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
            pre_patch_handler=pre_patch_handler,
        )

    def analyze_issue_with_context(
        self,
        *,
        selected_issue: RemediationExecutionTarget,
        context: IssueContext,
        dry_run: bool,
        pre_patch_handler: Callable[[PatchProposal], FailureDetails | None] | None = None,
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
        semantic_safety = self.semantic_safety_gate_service.decide(analysis)
        artifact_service.write_analysis(issue_key=selected_issue.source_ref, analysis=analysis)
        summary = (
            f"Analysis classification: {analysis.classification.value}. "
            f"Strategy: {analysis.proposed_strategy}"
        )
        relative_artifact_path = artifact_service.relative_path(self.repo_root)
        if relative_artifact_path is not None:
            summary = f"{summary}. Solution file: {relative_artifact_path}"
        if not semantic_safety.accepted:
            artifact_service.write_manual_rejection(issue_key=selected_issue.source_ref)
            reason = semantic_safety.reason or "Semantic-safety assessment was rejected."
            return AnalysisResult(
                summary=f"{summary}. Patch generation skipped: {reason}",
                validation_passed=False,
                semantic_safety=semantic_safety,
                terminal_rejection_stage=FailureStage.SEMANTIC_SAFETY,
            )
        try:
            patch = self._generate_patch(
                fix_generator=fix_generator,
                selected_issue=selected_issue,
                context=context.model_copy(
                    update={
                        "remediation_intent": analysis.remediation_intent,
                        "semantic_safety": semantic_safety.assessment,
                    }
                ),
                artifact_service=artifact_service,
                remediation_intent=analysis.remediation_intent,
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
            f"Change request title: {patch.change_request_title}."
        )
        should_apply_patch = not dry_run or self.config.apply_patch_in_dry_run
        if not should_apply_patch:
            return AnalysisResult(summary=summary, patch=patch)
        if pre_patch_handler is not None:
            preparation_failure = pre_patch_handler(patch)
            if preparation_failure is not None:
                return AnalysisResult(
                    summary=f"{summary}. {preparation_failure.message}",
                    patch=patch,
                    validation_passed=False,
                    failure=preparation_failure,
                )
        execution_result = self.patch_execution_service.execute(
            dry_run=dry_run,
            patch=patch,
            summary=summary,
            fix_generator=fix_generator,
            selected_issue=selected_issue,
            context=context,
            patch_factory=lambda **kwargs: self._generate_patch(
                artifact_service=artifact_service,
                fix_generator=kwargs["fix_generator"],
                selected_issue=kwargs["selected_issue"],
                context=kwargs["context"].model_copy(
                    update={"remediation_intent": analysis.remediation_intent}
                ),
                remediation_intent=analysis.remediation_intent,
            ),
        )
        return AnalysisResult(
            summary=execution_result.summary,
            patch=execution_result.patch,
            patch_applied=execution_result.patch_applied,
            validation_passed=execution_result.validation_passed,
            validation_result=execution_result.validation_result,
            validation_comparison=execution_result.validation_comparison,
            failure=execution_result.failure,
            workspace_snapshot=execution_result.workspace_snapshot,
            semantic_safety=semantic_safety,
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
        remediation_intent: str,
    ) -> PatchProposal:
        """Generate a patch proposal from a structured edit.

        Args:
            fix_generator: LLM-backed fix generator.
            selected_issue: Selected remediation target.
            context: Built issue context.
            artifact_service: Artifact persistence service for analysis outputs.
            remediation_intent: Analysis-derived intent that controls publication naming.

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
        patch = self.edit_renderer.render(structured_edit)
        return patch.model_copy(update={"remediation_intent": remediation_intent})
