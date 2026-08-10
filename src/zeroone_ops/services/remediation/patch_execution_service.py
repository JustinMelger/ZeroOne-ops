"""Patch execution service.

This module owns patch application, validation, retry, and rollback behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
from zeroone_ops.providers.llm_client import LLMClientError
from zeroone_ops.services.remediation.edit_renderer import EditRenderError
from zeroone_ops.services.remediation.fix_generator import FixGenerator
from zeroone_ops.services.remediation.patch_applier import (
    PatchApplier,
    PatchApplyError,
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
from zeroone_ops.services.shared.workspace_snapshot import (
    WorkspaceSnapshot,
    WorkspaceSnapshotService,
)


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
    """

    def __init__(
        self,
        *,
        config: AppConfig,
        patch_applier: PatchApplier,
        validator: Validator,
        workspace_snapshot_service: WorkspaceSnapshotService,
    ) -> None:
        """Initialize the patch execution service."""
        self.config = config
        self.patch_applier = patch_applier
        self.validator = validator
        self.workspace_snapshot_service = workspace_snapshot_service

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
        baseline = ValidationBaselineService(self.validator).capture(
            self.config.remediation.validation_commands
        )
        comparison_service = ValidationComparisonService()
        feedback_builder = ValidationFeedbackBuilder()
        allowed_files = tuple(sorted(set(patch.files_touched)))
        attempts = 1 if self.config.remediation.max_retry_count > 0 else 0

        for attempt in range(attempts + 1):
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
                    ),
                )

            post_edit = self.validator.run_all(self.config.remediation.validation_commands)
            comparison = comparison_service.compare(
                baseline=baseline,
                post_edit=post_edit,
                files_touched=patch.files_touched,
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
            if comparison.outcome == "actionable_regression" and attempt < attempts:
                feedback = feedback_builder.build(
                    comparison=comparison,
                    files_touched=patch.files_touched,
                )
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

            return PatchExecutionResult(
                summary=(
                    f"{summary}. "
                    f"{_validation_outcome_summary(comparison, correction_attempted=attempt > 0)}"
                ),
                patch=patch,
                patch_applied=False,
                validation_passed=False,
                validation_result=post_edit,
                workspace_snapshot=snapshot,
                validation_comparison=comparison,
                failure=_build_validation_failure(
                    validation_summary=_validation_outcome_summary(
                        comparison,
                        correction_attempted=attempt > 0,
                    ),
                    retry_count=attempt,
                    command_result=_first_failed_command(post_edit),
                    validation_outcome=comparison.outcome,
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
        if repository_status.stdout.strip():
            return _build_validation_bootstrap_failure(
                validation_summary=(
                    "Validation environment setup changed repository files. Setup commands must "
                    "leave tracked and non-ignored files untouched."
                ),
                command_result=repository_status.model_copy(update={"exit_code": 1}),
            )
        return None


def _build_validation_failure(
    *,
    validation_summary: str,
    retry_count: int,
    command_result: ValidationCommandResult | None,
    validation_outcome: ValidationOutcome | None = None,
) -> FailureDetails:
    """Build structured validation failure details."""
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
        validation_outcome=validation_outcome,
        failed_command=failed_command,
        exit_code=exit_code,
        stdout_excerpt=stdout_excerpt,
        stderr_excerpt=stderr_excerpt,
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
    message = f"Validation environment setup failed: {validation_summary}"
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


def _first_failed_command(result: ValidationResult) -> ValidationCommandResult | None:
    """Return the first failed command from complete validator evidence."""
    return next((command for command in result.results if command.exit_code != 0), None)


def _validation_outcome_summary(
    comparison: ValidationComparison,
    *,
    correction_attempted: bool = False,
) -> str:
    """Render the concise operator-facing validation outcome."""
    if comparison.outcome == "passed":
        return "Validation passed."
    if comparison.outcome == "baseline_preserved":
        return "Validation preserved the existing baseline failures."
    if comparison.outcome == "actionable_regression":
        diagnostic = comparison.new_relevant_diagnostics[0]
        retry_summary = (
            "one correction attempt was used."
            if correction_attempted
            else "no correction attempt was permitted."
        )
        return f"Validation introduced a new diagnostic in {diagnostic.file_path}; {retry_summary}"
    return "Validation failed outside the one-file repair boundary."
