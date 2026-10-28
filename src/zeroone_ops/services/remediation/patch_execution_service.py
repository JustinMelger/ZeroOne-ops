"""Patch execution service.

This module owns patch application, validation, retry, and rollback behavior.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from zeroone_ops.models.analysis import (
    IssueContext,
    PatchProposal,
    ValidationCommandResult,
    ValidationComparison,
    ValidationOutcome,
    ValidationResult,
)
from zeroone_ops.models.config import AppConfig
from zeroone_ops.models.remediation import RemediationExecutionTarget
from zeroone_ops.models.state import FailureDetails, FailureStage
from zeroone_ops.models.validation_evidence import ValidationAssessment
from zeroone_ops.providers.llm_client import LLMClientError
from zeroone_ops.services.remediation.edit_renderer import EditRenderError
from zeroone_ops.services.remediation.fix_generator import FixGenerator
from zeroone_ops.services.remediation.patch_applier import (
    PatchApplier,
    PatchApplyError,
)
from zeroone_ops.services.remediation.validation_feedback.failure_evidence import (
    failure_excerpt,
    sanitize_validation_text,
)
from zeroone_ops.services.remediation.validation_feedback.validation_baseline_service import (
    ValidationBaselineService,
)
from zeroone_ops.services.remediation.validation_feedback.validation_comparison_service import (
    ValidationComparisonService,
)
from zeroone_ops.services.remediation.validation_feedback.validation_feedback_builder import (
    ValidationFeedbackBuilder,
)
from zeroone_ops.services.remediation.validator import Validator
from zeroone_ops.services.shared.runtime_workspace import (
    RuntimeWorkspacePolicy,
    log_ignored_runtime_outputs,
    parse_porcelain_status,
)
from zeroone_ops.services.shared.workspace_snapshot import (
    WorkspaceSnapshot,
    WorkspaceSnapshotService,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PatchExecutionResult:
    """Capture the outcome of applying and validating a patch."""

    summary: str
    patch: PatchProposal
    patch_applied: bool
    validation_passed: bool
    validation_result: ValidationResult | None
    workspace_snapshot: WorkspaceSnapshot | None
    failure: FailureDetails | None = None
    validation_comparison: ValidationComparison | None = None


class PatchExecutionService:
    """Apply, validate, retry, and roll back patch proposals.

    Args:
        config: Loaded application configuration.
        patch_applier: Patch applier implementation.
        validator: Validation command runner.
        workspace_snapshot_service: Workspace snapshot service.
        runtime_workspace_policy: Shared rule for generated runtime outputs.
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        patch_applier: PatchApplier,
        validator: Validator,
        workspace_snapshot_service: WorkspaceSnapshotService,
        runtime_workspace_policy: RuntimeWorkspacePolicy | None = None,
    ) -> None:
        """Initialize the patch execution service."""
        self.config = config
        self.patch_applier = patch_applier
        self.validator = validator
        self.workspace_snapshot_service = workspace_snapshot_service
        self.runtime_workspace_policy = (
            runtime_workspace_policy
            or RuntimeWorkspacePolicy.from_config(
                config=config,
                repo_root=patch_applier.repo_root,
            )
        )

    def execute(
        self,
        *,
        dry_run: bool,
        patch: PatchProposal,
        summary: str,
        fix_generator: FixGenerator,
        selected_issue: RemediationExecutionTarget,
        context: IssueContext,
        patch_factory: Callable[..., PatchProposal],
    ) -> PatchExecutionResult:
        """Apply a patch locally and run configured validation commands."""
        LOGGER.info(
            "Validation baseline mode: enabled=%s",
            self.config.remediation.validation_feedback_enabled,
        )
        bootstrap_failure = self._bootstrap_validation_environment()
        if bootstrap_failure is not None:
            return PatchExecutionResult(
                summary=f"{summary}. {bootstrap_failure.message}",
                patch=patch,
                patch_applied=False,
                validation_passed=False,
                validation_result=None,
                workspace_snapshot=None,
                failure=bootstrap_failure,
            )
        if (
            self.config.remediation.validation_feedback_enabled
            and self.config.remediation.validation_commands
        ):
            return self._execute_with_validation_feedback(
                dry_run=dry_run,
                patch=patch,
                summary=summary,
                fix_generator=fix_generator,
                selected_issue=selected_issue,
                context=context,
                patch_factory=patch_factory,
            )
        for attempt in range(self.config.remediation.max_retry_count + 1):
            snapshot = self.workspace_snapshot_service.capture(patch.files_touched)
            try:
                self.patch_applier.validate(patch)
                self.patch_applier.apply(patch)
            except PatchApplyError as error:
                self.workspace_snapshot_service.restore(snapshot)
                return PatchExecutionResult(
                    summary=f"{summary}. Patch apply failed: {error}",
                    patch=patch,
                    patch_applied=False,
                    validation_passed=False,
                    validation_result=None,
                    workspace_snapshot=snapshot,
                    failure=FailureDetails(
                        stage=FailureStage.PATCH_APPLY,
                        message=f"Patch apply failed: {error}",
                        retry_count=attempt,
                        stdout_excerpt=_truncate_output(patch.unified_diff),
                    ),
                )

            validation_result = self.validator.run(self.config.remediation.validation_commands)
            if validation_result.passed:
                mode_label = "dry-run" if dry_run else "run"
                success_summary = (
                    f"{summary}. Patch applied locally in {mode_label}. {validation_result.summary}"
                )
                if attempt > 0:
                    success_summary = (
                        f"{summary}. Patch applied locally in {mode_label}. "
                        f"{validation_result.summary} after retry {attempt}."
                    )
                return PatchExecutionResult(
                    summary=success_summary,
                    patch=patch,
                    patch_applied=True,
                    validation_passed=True,
                    validation_result=validation_result,
                    workspace_snapshot=snapshot,
                )

            self.workspace_snapshot_service.restore(snapshot)
            if attempt >= self.config.remediation.max_retry_count:
                mode_label = "dry-run" if dry_run else "run"
                return PatchExecutionResult(
                    summary=(
                        f"{summary}. Patch applied locally in {mode_label}. "
                        f"{validation_result.summary} Retry attempts exhausted."
                    ),
                    patch=patch,
                    patch_applied=False,
                    validation_passed=False,
                    validation_result=validation_result,
                    workspace_snapshot=snapshot,
                    failure=_build_validation_failure(
                        validation_summary=validation_result.summary,
                        retry_count=attempt,
                        command_result=validation_result.results[-1]
                        if validation_result.results
                        else None,
                    ),
                )

            try:
                patch = patch_factory(
                    fix_generator=fix_generator,
                    selected_issue=selected_issue,
                    context=context,
                )
            except (EditRenderError, LLMClientError) as error:
                return PatchExecutionResult(
                    summary=f"{summary}. Structured edit generation failed during retry: {error}",
                    patch=patch,
                    patch_applied=False,
                    validation_passed=False,
                    validation_result=validation_result,
                    workspace_snapshot=snapshot,
                    failure=FailureDetails(
                        stage=FailureStage.ANALYSIS,
                        message=f"Structured edit generation failed during retry: {error}",
                        retry_count=attempt,
                    ),
                )

        return PatchExecutionResult(
            summary=summary,
            patch=patch,
            patch_applied=False,
            validation_passed=False,
            validation_result=None,
            workspace_snapshot=None,
        )

    def _execute_with_validation_feedback(
        self,
        *,
        dry_run: bool,
        patch: PatchProposal,
        summary: str,
        fix_generator: FixGenerator,
        selected_issue: RemediationExecutionTarget,
        context: IssueContext,
        patch_factory: Callable[..., PatchProposal],
    ) -> PatchExecutionResult:
        """Run the opt-in baseline-aware one-file validation feedback loop."""
        try:
            original_snapshot = self.workspace_snapshot_service.capture(patch.files_touched)
        except (OSError, UnicodeError):
            return _blocked_validation_evidence(
                summary=summary,
                patch=patch,
                reason="Validation source evidence could not be read.",
            )
        baseline = ValidationBaselineService(self.validator).capture(
            self.config.remediation.validation_commands
        )
        comparison_service = ValidationComparisonService()
        baseline_assessment = comparison_service.assess(
            baseline=baseline,
            post_edit=baseline.result,
            files_touched=patch.files_touched,
            expected_commands=self.config.remediation.validation_commands,
            repository_root=str(self.workspace_snapshot_service.repo_root.absolute()),
        )
        if baseline_assessment.problem is not None:
            baseline_failure = baseline_assessment.problem.reason
            LOGGER.info("Validation baseline blocked: %s", baseline_failure)
            return _blocked_validation_evidence(
                summary=summary,
                patch=patch,
                reason=baseline_failure,
                validation_result=baseline.result,
                workspace_snapshot=original_snapshot,
                validation_comparison=baseline_assessment.comparison,
                command_result=_assessment_failed_command(baseline_assessment),
                validation_phase="baseline",
            )
        feedback_builder = ValidationFeedbackBuilder()
        allowed_files = tuple(sorted(set(patch.files_touched)))
        attempts = 1 if self.config.remediation.max_retry_count > 0 else 0

        for attempt in range(attempts + 1):
            snapshot = original_snapshot
            try:
                self.patch_applier.validate(patch)
                self.patch_applier.apply(patch)
            except PatchApplyError as error:
                self.workspace_snapshot_service.restore(snapshot)
                return PatchExecutionResult(
                    summary=f"{summary}. Patch apply failed: {error}",
                    patch=patch,
                    patch_applied=False,
                    validation_passed=False,
                    validation_result=None,
                    workspace_snapshot=snapshot,
                    failure=FailureDetails(
                        stage=FailureStage.PATCH_APPLY,
                        message=f"Patch apply failed: {error}",
                        retry_count=attempt,
                    ),
                )

            post_edit = self.validator.run_all(self.config.remediation.validation_commands)
            try:
                source_changes = self.workspace_snapshot_service.source_changes(original_snapshot)
            except (OSError, UnicodeError):
                self.workspace_snapshot_service.restore(snapshot)
                return _blocked_validation_evidence(
                    summary=summary,
                    patch=patch,
                    reason="Validation source evidence could not be read.",
                    validation_result=post_edit,
                    workspace_snapshot=snapshot,
                    retry_count=attempt,
                )
            assessment = comparison_service.assess(
                baseline=baseline,
                post_edit=post_edit,
                files_touched=patch.files_touched,
                source_changes=source_changes,
                expected_commands=self.config.remediation.validation_commands,
                repository_root=str(self.workspace_snapshot_service.repo_root.absolute()),
            )
            comparison = assessment.comparison
            LOGGER.info(
                "Validation comparison: outcome=%s reason=%s",
                comparison.outcome,
                comparison.blocking_reason or "diagnostic comparison complete",
            )
            if comparison.allows_publication:
                mode_label = "dry-run" if dry_run else "run"
                outcome_summary = _validation_outcome_summary(comparison)
                return PatchExecutionResult(
                    summary=f"{summary}. Patch applied locally in {mode_label}. {outcome_summary}",
                    patch=patch,
                    patch_applied=True,
                    validation_passed=comparison.outcome == "passed",
                    validation_result=post_edit,
                    workspace_snapshot=snapshot,
                    validation_comparison=comparison,
                )

            self.workspace_snapshot_service.restore(snapshot)
            feedback = feedback_builder.build(
                assessment=assessment, files_touched=patch.files_touched
            )
            if assessment.correction.eligible and feedback is not None and attempt < attempts:
                try:
                    regenerated_context = context.model_copy(
                        update={"validation_feedback": feedback}
                    )
                    regenerated_patch = patch_factory(
                        fix_generator=fix_generator,
                        selected_issue=selected_issue,
                        context=regenerated_context,
                    )
                    if tuple(sorted(set(regenerated_patch.files_touched))) != allowed_files:
                        raise EditRenderError(
                            "Validation-feedback retry must preserve the original one-file scope."
                        )
                    patch = regenerated_patch
                    continue
                except (EditRenderError, LLMClientError) as error:
                    return PatchExecutionResult(
                        summary=(
                            f"{summary}. Structured edit generation failed during validation "
                            f"feedback: {error}"
                        ),
                        patch=patch,
                        patch_applied=False,
                        validation_passed=False,
                        validation_result=post_edit,
                        workspace_snapshot=snapshot,
                        validation_comparison=comparison,
                        failure=FailureDetails(
                            stage=FailureStage.ANALYSIS,
                            message=(
                                "Structured edit generation failed during validation feedback: "
                                f"{error}"
                            ),
                            retry_count=attempt,
                            validation_outcome=comparison.outcome,
                        ),
                    )

            correction_summary = _correction_summary(
                assessment, attempt, attempts, feedback is not None
            )
            failure_summary = f"{_validation_outcome_summary(comparison)} {correction_summary}"
            return PatchExecutionResult(
                summary=(f"{summary}. {failure_summary}"),
                patch=patch,
                patch_applied=False,
                validation_passed=False,
                validation_result=post_edit,
                workspace_snapshot=snapshot,
                validation_comparison=comparison,
                failure=_build_validation_failure(
                    validation_summary=failure_summary,
                    retry_count=attempt,
                    command_result=_assessment_failed_command(assessment),
                    validation_outcome=comparison.outcome,
                    validation_phase="post_edit",
                    baseline_exit_code=_assessment_baseline_exit(assessment),
                ),
            )

        raise AssertionError("Validation feedback attempts must return a result.")

    def _bootstrap_validation_environment(self) -> FailureDetails | None:
        """Prepare configured validation tooling once before patch execution."""
        if (
            not self.config.remediation.validation_commands
            or not self.config.remediation.validation_setup_commands
        ):
            return None
        setup_result = self.validator.run(self.config.remediation.validation_setup_commands)
        if not setup_result.passed:
            failed_command = setup_result.results[-1] if setup_result.results else None
            return _build_validation_bootstrap_failure(
                validation_summary=setup_result.summary,
                command_result=failed_command,
                workspace_may_be_dirty=True,
            )
        repository_status = self.validator.repository_status()
        if repository_status.exit_code != 0:
            return _build_validation_bootstrap_failure(
                validation_summary=(
                    "Validation environment setup could not verify repository state."
                ),
                command_result=repository_status,
            )
        changes = parse_porcelain_status(repository_status.stdout)
        blocking_changes, ignored_runtime_outputs = self.runtime_workspace_policy.split_changes(
            changes
        )
        log_ignored_runtime_outputs(ignored_runtime_outputs)
        if blocking_changes:
            return _build_validation_bootstrap_failure(
                validation_summary=(
                    "Validation environment setup changed repository files. Setup commands must "
                    "leave tracked and non-ignored files untouched."
                ),
                command_result=repository_status.model_copy(update={"exit_code": 1}),
            )
        return None


def _blocked_validation_evidence(
    *,
    summary: str,
    patch: PatchProposal,
    reason: str,
    validation_result: ValidationResult | None = None,
    workspace_snapshot: WorkspaceSnapshot | None = None,
    validation_comparison: ValidationComparison | None = None,
    retry_count: int = 0,
    command_result: ValidationCommandResult | None = None,
    validation_phase: Literal["baseline", "post_edit"] | None = None,
) -> PatchExecutionResult:
    """Unusable baseline/source evidence blocks without model regeneration."""
    return PatchExecutionResult(
        summary=f"{summary}. {reason}",
        patch=patch,
        patch_applied=False,
        validation_passed=False,
        validation_result=validation_result,
        workspace_snapshot=workspace_snapshot,
        validation_comparison=validation_comparison,
        failure=_build_validation_failure(
            validation_summary=reason,
            retry_count=retry_count,
            command_result=command_result,
            validation_outcome="unscoped_regression",
            validation_phase=validation_phase,
            baseline_exit_code=command_result.exit_code if command_result else None,
        ),
    )


def _assessment_failed_command(assessment: ValidationAssessment) -> ValidationCommandResult | None:
    """Select the actual blocker, not an earlier baseline-preserved failed command."""
    problem = assessment.problem
    if problem is None or problem.command_index is None:
        return None
    result = (
        assessment.comparison.baseline
        if problem.phase == "baseline"
        else assessment.comparison.post_edit
    )
    return result.results[problem.command_index]


def _assessment_baseline_exit(assessment: ValidationAssessment) -> int | None:
    problem = assessment.problem
    if problem is None or problem.command_index is None:
        return None
    return assessment.comparison.baseline.results[problem.command_index].exit_code


def _correction_summary(
    assessment: ValidationAssessment,
    attempt: int,
    attempts: int,
    has_feedback: bool,
) -> str:
    if attempt:
        return "One correction attempt was used; final validation still blocks publication."
    if not assessment.correction.eligible:
        return "Correction withheld because validation evidence is not eligible."
    if not attempts:
        return "No correction attempt was permitted by configuration."
    if not has_feedback:
        return "Correction withheld because usable feedback could not fit the evidence budget."
    return "Validation blocks publication."


def _build_validation_failure(
    *,
    validation_summary: str,
    retry_count: int,
    command_result: ValidationCommandResult | None,
    validation_outcome: ValidationOutcome | None = None,
    validation_phase: Literal["baseline", "post_edit"] | None = None,
    baseline_exit_code: int | None = None,
) -> FailureDetails:
    """Build structured validation failure details."""
    failed_command = None
    exit_code = None
    diagnostic_excerpt = None
    if command_result is not None:
        failed_command = sanitize_validation_text(command_result.command).replace("\n", " ")
        exit_code = command_result.exit_code
        diagnostic_excerpt = failure_excerpt(command_result.stdout, command_result.stderr)
    return FailureDetails(
        stage=FailureStage.VALIDATION,
        message=sanitize_validation_text(validation_summary),
        retry_count=retry_count,
        validation_summary=sanitize_validation_text(validation_summary),
        validation_outcome=validation_outcome,
        failed_command=failed_command,
        exit_code=exit_code,
        validation_phase=validation_phase,
        baseline_exit_code=baseline_exit_code,
        diagnostic_excerpt=diagnostic_excerpt,
    )


def _build_validation_bootstrap_failure(
    *,
    validation_summary: str,
    command_result: ValidationCommandResult | None,
    workspace_may_be_dirty: bool = False,
) -> FailureDetails:
    """Build structured diagnostics when validation environment setup fails."""
    failure = _build_validation_failure(
        validation_summary=validation_summary,
        retry_count=0,
        command_result=command_result,
    )
    message = f"Validation environment setup failed: {sanitize_validation_text(validation_summary)}"
    if workspace_may_be_dirty:
        message = f"{message} Inspect the workspace before retrying."
    return failure.model_copy(
        update={
            "stage": FailureStage.VALIDATION_SETUP,
            "message": message,
        }
    )


def _truncate_output(value: str, limit: int = 500) -> str | None:
    """Truncate command output for state persistence."""
    stripped = value.strip()
    if not stripped:
        return None
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[:limit]}..."


def _validation_outcome_summary(comparison: ValidationComparison) -> str:
    """Render the concise operator-facing validation outcome."""
    if comparison.outcome == "passed":
        return "Validation passed."
    if comparison.outcome == "baseline_preserved":
        return "Validation preserved the existing baseline failures."
    if comparison.outcome == "actionable_regression":
        diagnostic = comparison.new_relevant_diagnostics[0]
        return f"Validation introduced a new diagnostic in {diagnostic.file_path}."
    return comparison.blocking_reason or "Validation failed outside the one-file repair boundary."
